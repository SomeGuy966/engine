"""Builds the comparison image for multi-model runs: the original (plainly
enlarged, as the "before") followed by each model's result, laid out in a
labeled grid and saved as one PNG."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAX_SHEET_MEGAPIXELS = 60   # big enough to zoom into, small enough to open quickly
_FONTS = ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
          "/Library/Fonts/Arial.ttf", "DejaVuSans.ttf")


def _font(size: int):
    for f in _FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _columns(n: int) -> int:
    return n if n <= 3 else math.ceil(math.sqrt(n))


def make_comparison_sheet(original: Image.Image, results: list, out_path: Path) -> Path:
    """``results`` are core.Result objects (all the same output size)."""
    w, h = results[0].output_size
    tiles = [("Before (original, plain enlargement)",
              original.convert("RGB").resize((w, h), Image.Resampling.LANCZOS))]
    for r in results:
        with Image.open(r.output_path) as im:
            tile = im.convert("RGBA")
            flat = Image.new("RGB", tile.size, "white")
            flat.paste(tile, mask=tile.getchannel("A"))
        if flat.size != (w, h):
            flat = flat.resize((w, h), Image.Resampling.LANCZOS)
        tiles.append((f"{r.model_name}  ·  {r.seconds:g}s", flat))

    n = len(tiles)
    cols = _columns(n)
    rows = math.ceil(n / cols)
    label_h = max(36, h // 18)
    gap = max(6, w // 200)
    full_w = cols * w + (cols - 1) * gap
    full_h = rows * (h + label_h) + (rows - 1) * gap
    shrink = min(1.0, math.sqrt(MAX_SHEET_MEGAPIXELS * 1e6 / (full_w * full_h)))
    tw, th = max(1, round(w * shrink)), max(1, round(h * shrink))
    label_h, gap = max(24, round(label_h * shrink)), max(4, round(gap * shrink))

    sheet = Image.new("RGB", (cols * tw + (cols - 1) * gap, rows * (th + label_h) + (rows - 1) * gap), (24, 24, 27))
    draw = ImageDraw.Draw(sheet)
    font = _font(round(label_h * 0.55))
    for i, (label, img) in enumerate(tiles):
        cx, cy = (i % cols) * (tw + gap), (i // cols) * (th + label_h + gap)
        draw.rectangle((cx, cy, cx + tw - 1, cy + label_h - 1), fill=(10, 102, 216) if i else (70, 70, 76))
        draw.text((cx + label_h // 3, cy + label_h // 2), label, fill="white", font=font, anchor="lm")
        sheet.paste(img if shrink == 1.0 else img.resize((tw, th), Image.Resampling.LANCZOS), (cx, cy + label_h))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, compress_level=4)
    return out_path
