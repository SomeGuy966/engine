"""The fixed core: open image -> hand it to whichever backend the chosen card
names -> resize to the exact target -> save. Switching models never changes
this file."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .backends import Backend, Cancelled, Report, backend_class
from .cards import ModelCard, find_card, load_cards
from .paths import IMAGE_SUFFIXES, OUTPUT_DIR, ensure_dirs

Image.MAX_IMAGE_PIXELS = 400_000_000  # allow big outputs, still guards against absurd files
MAX_OUTPUT_MEGAPIXELS = 120


@dataclass
class Result:
    output_path: str
    model_id: str
    model_name: str
    scale: float
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt_scale(scale: float) -> str:
    return f"{scale:g}".replace(".", "_")


def _unique_output_path(src: Path, card: ModelCard, scale: float, output_dir: Path) -> Path:
    base = f"{src.stem}__{card.id}_{_fmt_scale(scale)}x"
    out = output_dir / f"{base}.png"
    n = 2
    while out.exists():
        out = output_dir / f"{base}-{n}.png"
        n += 1
    return out


def open_image(path: str | Path) -> Image.Image:
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"No file at {path}")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"{path.name} doesn't look like an image ({', '.join(sorted(IMAGE_SUFFIXES))})")
    img = Image.open(path)
    img.load()
    return ImageOps.exif_transpose(img)


class Engine:
    """Keeps at most one model loaded at a time (to spare your Mac's memory)."""

    def __init__(self) -> None:
        self._backend: Backend | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.last_used = time.time()

    # -- model management -------------------------------------------------
    def _backend_for(self, card: ModelCard, report: Report) -> Backend:
        if self._backend and self._backend.card.id == card.id and self._backend.card == card:
            return self._backend
        self.unload()
        backend = backend_class(card.backend)(card)
        backend.load(report)
        self._backend = backend
        return backend

    def unload(self) -> None:
        if self._backend:
            try:
                self._backend.unload()
            finally:
                self._backend = None

    def unload_if_idle(self, idle_seconds: float) -> None:
        """Free the model's memory if nothing has run for a while (never mid-run)."""
        if self._backend and time.time() - self.last_used > idle_seconds and self._lock.acquire(blocking=False):
            try:
                self.unload()
            finally:
                self._lock.release()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    # -- the one thing the engine does -----------------------------------
    def enhance(
        self,
        input_path: str | Path,
        model: str | None = None,
        scale: float | None = None,
        output_dir: str | Path | None = None,
        report: Report | None = None,
    ) -> Result:
        user_report = report or (lambda frac, msg: None)

        def checked_report(frac, msg):
            if self._cancel.is_set():
                raise Cancelled("Cancelled")
            user_report(frac, msg)

        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Already enhancing an image - wait for it to finish.")
        try:
            self._cancel.clear()
            ensure_dirs()
            started = time.time()
            cards, _ = load_cards()
            card = find_card(model, cards)
            if not card.available:
                raise FileNotFoundError(
                    f"Model '{card.name}' is missing: {', '.join(card.missing_files)}. "
                    "Run ./setup.sh (or see README: Adding a model)."
                )
            scale = float(scale or card.default_scale)
            if not (1 < scale <= card.max_scale):
                raise ValueError(f"Scale must be more than 1 and at most {card.max_scale:g} for {card.name}")

            src = Path(input_path).expanduser().resolve()
            img = open_image(src)
            w, h = img.size
            target = (round(w * scale), round(h * scale))
            if target[0] * target[1] > MAX_OUTPUT_MEGAPIXELS * 1e6:
                raise ValueError(
                    f"{target[0]}x{target[1]} would be over {MAX_OUTPUT_MEGAPIXELS} megapixels - pick a smaller scale."
                )

            # keep transparency (if any) by enlarging the alpha channel separately
            alpha = None
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                rgba = img.convert("RGBA")
                if rgba.getchannel("A").getextrema() != (255, 255):
                    alpha = rgba.getchannel("A")
                rgb = rgba.convert("RGB")
            else:
                rgb = img.convert("RGB")

            checked_report(0.0, f"{card.name}: {w}x{h} -> {target[0]}x{target[1]}")
            backend = self._backend_for(card, checked_report)
            out = backend.upscale(rgb, scale, checked_report)
            if out.size != target:
                out = out.resize(target, Image.Resampling.LANCZOS)
            if alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha.resize(target, Image.Resampling.LANCZOS))

            checked_report(None, "Saving")
            out_dir = Path(output_dir).expanduser() if output_dir else OUTPUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = _unique_output_path(src, card, scale, out_dir)
            out.save(out_path, compress_level=4)
            user_report(1.0, f"Saved {out_path.name}")
            return Result(
                output_path=str(out_path),
                model_id=card.id,
                model_name=card.name,
                scale=scale,
                input_size=(w, h),
                output_size=target,
                seconds=round(time.time() - started, 1),
            )
        finally:
            self.last_used = time.time()
            self._lock.release()
