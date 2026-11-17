"""Runs classic single-pass upscale models through Spandrel.

Spandrel recognises hundreds of model files automatically - Real-ESRGAN,
UltraSharp, SwinIR, HAT, DAT, RealPLKSR, SPAN, and more - so any model from
https://openmodeldb.info can be used by dropping its file into models/weights/.

The image is processed in overlapping tiles so memory stays low no matter how
big the picture is.
"""

from __future__ import annotations

import math

import numpy as np
import torch
from PIL import Image
from spandrel import ImageModelDescriptor, ModelLoader

from .base import Backend, Report


def _device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class SpandrelBackend(Backend):
    name = "spandrel"

    def load(self, report: Report) -> None:
        path = self.card.weights_path
        report(None, f"Loading {path.name}")
        desc = ModelLoader(device="cpu").load_from_file(str(path))
        if not isinstance(desc, ImageModelDescriptor):
            raise ValueError(f"{path.name} is not an image-to-image model")
        self.device = _device()
        self.half = bool(self.card.options.get("half", False)) and desc.supports_half
        desc.to(self.device).eval()
        if self.half:
            desc.half()
        self.model = desc
        self.native_scale = desc.scale
        report(None, f"Loaded {desc.architecture.name} ({desc.scale}x) on {self.device.type.upper()}")

    def unload(self) -> None:
        self.model = None
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    @torch.inference_mode()
    def upscale(self, image: Image.Image, scale: float, report: Report) -> Image.Image:
        s = self.native_scale
        tile = int(self.card.options.get("tile", 512))
        overlap = int(self.card.options.get("overlap", 32))
        dtype = torch.float16 if self.half else torch.float32

        arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        x = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)  # 1,3,H,W on CPU
        _, _, H, W = x.shape
        out = torch.empty((1, 3, H * s, W * s), dtype=torch.float32)

        tiles_y, tiles_x = math.ceil(H / tile), math.ceil(W / tile)
        total, done = tiles_y * tiles_x, 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                y, xx = ty * tile, tx * tile
                y1, x1 = min(y + tile, H), min(xx + tile, W)
                # input window = tile plus overlap on every side (clamped to the image)
                py0, px0 = max(y - overlap, 0), max(xx - overlap, 0)
                py1, px1 = min(y1 + overlap, H), min(x1 + overlap, W)
                patch = x[:, :, py0:py1, px0:px1].to(self.device, dtype)
                res = self.model(patch).float().cpu()
                # keep only the centre (drop the overlap margins)
                oy, ox = (y - py0) * s, (xx - px0) * s
                out[:, :, y * s:y1 * s, xx * s:x1 * s] = res[:, :, oy:oy + (y1 - y) * s, ox:ox + (x1 - xx) * s]
                done += 1
                report(done / total, f"Tile {done}/{total}")

        if self.device.type == "mps":
            torch.mps.empty_cache()
        result = (out.squeeze(0).clamp_(0, 1).permute(1, 2, 0).numpy() * 255.0).round().astype(np.uint8)
        return Image.fromarray(result, "RGB")
