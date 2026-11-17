"""The fixed core: open image -> hand it to whichever backend the chosen card
names -> resize to the exact target -> save. Switching models never changes
this file.

``enhance`` runs one model. ``enhance_many`` runs several models on the same
image, one after another, and also saves a side-by-side comparison image.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
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


@dataclass
class MultiResult:
    results: list[Result]
    comparison_path: str | None = None
    errors: list[dict] = field(default_factory=list)   # [{model_id, model_name, error}]
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "comparison_path": self.comparison_path,
            "errors": self.errors,
            "seconds": self.seconds,
        }


def _fmt_scale(scale: float) -> str:
    return f"{scale:g}".replace(".", "_")


def _unique_path(output_dir: Path, base: str) -> Path:
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

    # -- running ----------------------------------------------------------
    @contextmanager
    def _session(self):
        """One run at a time; resets the Cancel button; frees the lock afterwards."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Already enhancing an image - wait for it to finish.")
        try:
            self._cancel.clear()
            ensure_dirs()
            yield
        finally:
            self.last_used = time.time()
            self._lock.release()

    def _checked(self, report: Report | None) -> Report:
        user_report = report or (lambda frac, msg: None)

        def checked(frac, msg):
            if self._cancel.is_set():
                raise Cancelled("Cancelled")
            user_report(frac, msg)

        return checked

    def enhance(
        self,
        input_path: str | Path,
        model: str | None = None,
        scale: float | None = None,
        output_dir: str | Path | None = None,
        report: Report | None = None,
    ) -> Result:
        """Enhance one image with one model."""
        with self._session():
            return self._enhance(input_path, model, scale, output_dir, self._checked(report))

    def enhance_many(
        self,
        input_path: str | Path,
        models: list[str],
        scale: float | None = None,
        output_dir: str | Path | None = None,
        report: Report | None = None,
    ) -> MultiResult:
        """Enhance one image with several models (one after another) and save a
        comparison image of all the results. With a single model this is the
        same as ``enhance``."""
        from .compare import make_comparison_sheet

        with self._session():
            started = time.time()
            check = self._checked(report)
            cards, _ = load_cards()
            chosen: list[ModelCard] = []
            for m in models:
                c = find_card(m, cards)
                if c.id not in {x.id for x in chosen}:
                    chosen.append(c)
            if not chosen:
                raise ValueError("Pick at least one model.")
            if len(chosen) == 1:
                r = self._enhance(input_path, chosen[0].id, scale, output_dir, check)
                return MultiResult(results=[r], seconds=r.seconds)

            missing = [c.name for c in chosen if not c.available]
            if missing:
                raise FileNotFoundError(f"Not downloaded yet: {', '.join(missing)}. Run ./setup.sh.")
            scale = float(scale or min(c.default_scale for c in chosen))
            limit = min(c.max_scale for c in chosen)
            if not (1 < scale <= limit):
                raise ValueError(f"With these models, scale must be more than 1 and at most {limit:g}.")

            n = len(chosen)
            results: list[Result] = []
            errors: list[dict] = []
            for i, card in enumerate(chosen):
                def sub(frac, msg, i=i, card=card):
                    overall = None if frac is None else (i + min(max(frac, 0.0), 1.0)) / n
                    check(overall, f"[{i + 1}/{n}] {card.name}: {msg}" if msg else None)

                try:
                    results.append(self._enhance(input_path, card.id, scale, output_dir, sub))
                except Cancelled:
                    raise
                except Exception as e:  # one model failing shouldn't lose the others
                    errors.append({"model_id": card.id, "model_name": card.name, "error": str(e)})
                    check(None, f"[{i + 1}/{n}] {card.name} failed: {e}")

            comparison = None
            if results:
                check(None, "Building the comparison image")
                src = Path(input_path).expanduser().resolve()
                out_dir = Path(output_dir).expanduser() if output_dir else OUTPUT_DIR
                out_path = _unique_path(out_dir, f"{src.stem}__compare_{_fmt_scale(scale)}x")
                make_comparison_sheet(open_image(src), results, out_path)
                comparison = str(out_path)
                check(1.0, f"Saved {out_path.name}")
            return MultiResult(results=results, comparison_path=comparison, errors=errors,
                               seconds=round(time.time() - started, 1))

    def _enhance(self, input_path, model, scale, output_dir, report: Report) -> Result:
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

        report(0.0, f"{card.name}: {w}x{h} -> {target[0]}x{target[1]}")
        backend = self._backend_for(card, report)
        out = backend.upscale(rgb, scale, report)
        if out.size != target:
            out = out.resize(target, Image.Resampling.LANCZOS)
        if alpha is not None:
            out = out.convert("RGBA")
            out.putalpha(alpha.resize(target, Image.Resampling.LANCZOS))

        report(None, "Saving")
        out_dir = Path(output_dir).expanduser() if output_dir else OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = _unique_path(out_dir, f"{src.stem}__{card.id}_{_fmt_scale(scale)}x")
        out.save(out_path, compress_level=4)
        report(1.0, f"Saved {out_path.name}")
        return Result(
            output_path=str(out_path),
            model_id=card.id,
            model_name=card.name,
            scale=scale,
            input_size=(w, h),
            output_size=target,
            seconds=round(time.time() - started, 1),
        )
