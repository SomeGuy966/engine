"""The contract every backend follows.

A *backend* knows how to run one family of models (the "body type").
A *card* picks a specific model for that backend (the "outfit").
The core only ever talks to backends through this small interface.
"""

from __future__ import annotations

from typing import Callable, Optional

from PIL import Image

from ..cards import ModelCard

# report(fraction, message): fraction is 0..1 (or None if unknown); message is a
# short human-readable status line (or None). Calling it may raise Cancelled.
Report = Callable[[Optional[float], Optional[str]], None]


class Cancelled(Exception):
    pass


class Backend:
    name = "base"

    def __init__(self, card: ModelCard):
        self.card = card

    def load(self, report: Report) -> None:
        """Load the model into memory. Called once before the first upscale."""

    def upscale(self, image: Image.Image, scale: float, report: Report) -> Image.Image:
        """Return an enlarged RGB image. It may be any size; the core resizes the
        result to exactly (width*scale, height*scale) afterwards."""
        raise NotImplementedError

    def unload(self) -> None:
        """Free memory. Called when switching to another model or when idle."""
