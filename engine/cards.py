"""Model cards - the "outfits".

Every ``models/<id>.toml`` file describes one model: its display name, which
backend runs it, and which weight file(s) it needs. The engine core never
changes; adding, removing, or switching a model only touches these cards.

As a shortcut, any loose ``.pth`` / ``.safetensors`` file dropped straight into
``models/weights/`` (with no card pointing at it) shows up automatically as a
model run by the ``spandrel`` backend.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import MODELS_DIR, WEIGHTS_DIR

WEIGHT_SUFFIXES = (".pth", ".pt", ".safetensors", ".ckpt")
KNOWN_BACKENDS = ("resize", "spandrel", "seedvr2")


class CardError(Exception):
    pass


@dataclass
class ModelFile:
    """One downloadable file a model needs (path is relative to models/weights/)."""

    path: str
    url: str | None = None
    sha256: str | None = None

    @property
    def local(self) -> Path:
        return WEIGHTS_DIR / self.path


@dataclass
class ModelCard:
    id: str
    name: str
    backend: str
    weights: str | None = None          # main weight file, relative to models/weights/
    description: str = ""
    best_for: str = ""
    speed: str = ""
    default_scale: float = 2.0
    max_scale: float = 4.0
    order: int = 100
    default: bool = False
    license: str = ""
    source: str = ""
    options: dict = field(default_factory=dict)   # backend-specific knobs
    files: list[ModelFile] = field(default_factory=list)
    card_path: Path | None = None
    auto: bool = False                  # True if discovered from a loose weight file

    @property
    def weights_path(self) -> Path | None:
        return WEIGHTS_DIR / self.weights if self.weights else None

    @property
    def required_paths(self) -> list[str]:
        paths = {f.path for f in self.files}
        if self.weights:
            paths.add(self.weights)
        return sorted(paths)

    @property
    def missing_files(self) -> list[str]:
        return [p for p in self.required_paths if not (WEIGHTS_DIR / p).exists()]

    @property
    def available(self) -> bool:
        return not self.missing_files

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "backend": self.backend,
            "description": self.description,
            "best_for": self.best_for,
            "speed": self.speed,
            "default_scale": self.default_scale,
            "max_scale": self.max_scale,
            "default": self.default,
            "available": self.available,
            "missing_files": self.missing_files,
            "license": self.license,
            "auto": self.auto,
        }


def _parse_card(path: Path) -> ModelCard:
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise CardError(f"{path.name}: not valid TOML ({e})") from e
    for key in ("name", "backend"):
        if key not in data:
            raise CardError(f"{path.name}: missing required field '{key}'")
    if data["backend"] not in KNOWN_BACKENDS:
        raise CardError(
            f"{path.name}: unknown backend '{data['backend']}' "
            f"(choose one of: {', '.join(KNOWN_BACKENDS)})"
        )
    files = [ModelFile(**f) for f in data.pop("files", [])]
    known = set(ModelCard.__dataclass_fields__) - {"id", "files", "card_path", "auto"}
    unknown = set(data) - known
    if unknown:
        raise CardError(f"{path.name}: unknown field(s) {', '.join(sorted(unknown))}")
    return ModelCard(id=path.stem, files=files, card_path=path, **data)


def load_cards() -> tuple[list[ModelCard], list[str]]:
    """Return (cards sorted for display, list of problems found)."""
    cards: list[ModelCard] = []
    problems: list[str] = []
    for path in sorted(MODELS_DIR.glob("*.toml")):
        try:
            cards.append(_parse_card(path))
        except (CardError, TypeError) as e:
            problems.append(str(e))

    # Auto-discover loose weight files that no card mentions.
    referenced = {p for c in cards for p in c.required_paths}
    taken_ids = {c.id for c in cards}
    if WEIGHTS_DIR.exists():
        for f in sorted(WEIGHTS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in WEIGHT_SUFFIXES and f.name not in referenced:
                cid = f.stem if f.stem not in taken_ids else f"{f.stem}-auto"
                cards.append(
                    ModelCard(
                        id=cid,
                        name=f"{f.stem}",
                        backend="spandrel",
                        weights=f.name,
                        description="Dropped-in model file (no card yet). Runs with the spandrel backend.",
                        order=900,
                        auto=True,
                    )
                )

    cards.sort(key=lambda c: (c.order, c.name.lower()))
    if cards and not any(c.default for c in cards):
        next((c for c in cards if c.available), cards[0]).default = True
    return cards, problems


def find_card(model: str | None, cards: list[ModelCard] | None = None) -> ModelCard:
    """Look up a card by id (exact, then unique prefix, case-insensitive). None = default."""
    if cards is None:
        cards, _ = load_cards()
    if not cards:
        raise CardError("No models found. Add a card to the models/ folder.")
    if not model:
        return next(c for c in cards if c.default)
    m = model.lower()
    for c in cards:
        if c.id.lower() == m:
            return c
    matches = [c for c in cards if c.id.lower().startswith(m) or c.name.lower().startswith(m)]
    if len(matches) == 1:
        return matches[0]
    ids = ", ".join(c.id for c in cards)
    if matches:
        raise CardError(f"'{model}' matches several models: {', '.join(c.id for c in matches)}")
    raise CardError(f"No model called '{model}'. Available: {ids}")
