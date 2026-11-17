"""Plain (non-AI) resizing. Useful as a baseline to compare the AI models against,
and the most honest choice for screenshots that are mostly small text."""

from __future__ import annotations

from PIL import Image

from .base import Backend, Report

_FILTERS = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "nearest": Image.Resampling.NEAREST,
}


class ResizeBackend(Backend):
    name = "resize"

    def upscale(self, image: Image.Image, scale: float, report: Report) -> Image.Image:
        method = self.card.options.get("filter", "lanczos")
        w, h = image.size
        report(0.5, f"Resizing with {method}")
        return image.resize((round(w * scale), round(h * scale)), _FILTERS[method])
