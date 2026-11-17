"""Runs SeedVR2 (one-step diffusion upscaler) through its official command-line
runner in vendor/SeedVR2.

It runs as a separate process on purpose: when it finishes, all of its memory
(several GB) goes straight back to macOS, which matters on a 16 GB Mac.
"""

from __future__ import annotations

import math
import os
import queue
import re
import subprocess
import tempfile
import threading
from collections import deque

from PIL import Image

from ..paths import PYTHON, UPLOADS_DIR, VENDOR_DIR
from .base import Backend, Report

RUNNER = VENDOR_DIR / "SeedVR2" / "inference_cli.py"
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class SeedVR2Backend(Backend):
    name = "seedvr2"

    def load(self, report: Report) -> None:
        if not RUNNER.exists():
            raise FileNotFoundError(
                f"SeedVR2 runner not found at {RUNNER}. Run ./setup.sh to install it."
            )

    def upscale(self, image: Image.Image, scale: float, report: Report) -> Image.Image:
        opts = self.card.options
        w, h = image.size
        max_mp = float(opts.get("max_output_megapixels", 8))
        eff = scale
        if w * h * scale * scale > max_mp * 1e6:
            eff = math.sqrt(max_mp * 1e6 / (w * h))
            report(None, (
                f"Note: SeedVR2 is capped at about {max_mp:g} MP on this Mac, so it will "
                f"generate {eff:.2f}x and plain resizing will make up the rest."
            ))
        short_side = round(min(w, h) * eff)
        short_side -= short_side % 2

        weights = self.card.weights_path
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="seedvr2_", dir=UPLOADS_DIR) as td:
            src, dst = os.path.join(td, "input.png"), os.path.join(td, "output.png")
            image.save(src)
            cmd = [
                str(PYTHON), str(RUNNER), src,
                "--output", dst,
                "--output_format", "png",
                "--model_dir", str(weights.parent),
                "--dit_model", weights.name,
                "--resolution", str(short_side),
                "--batch_size", "1",
                "--seed", str(opts.get("seed", 42)),
                "--color_correction", str(opts.get("color_correction", "lab")),
            ]
            if opts.get("vae_tiling", True):
                tile = str(opts.get("vae_tile_size", 1024))
                cmd += ["--vae_encode_tiled", "--vae_encode_tile_size", tile,
                        "--vae_decode_tiled", "--vae_decode_tile_size", tile]
            env = dict(os.environ,
                       PYTHONUNBUFFERED="1",
                       PYTORCH_ENABLE_MPS_FALLBACK="1",
                       HF_HUB_OFFLINE="1",            # never reach out to the internet
                       HF_HUB_DISABLE_TELEMETRY="1",
                       DO_NOT_TRACK="1")
            report(None, f"Starting SeedVR2 ({weights.name}) -> short side {short_side}px")
            proc = subprocess.Popen(cmd, cwd=str(RUNNER.parent), env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
            tail: deque[str] = deque(maxlen=25)
            lines: queue.Queue = queue.Queue()

            def pump():  # read output in the background so Cancel works even when SeedVR2 is quiet
                for raw in proc.stdout:
                    lines.put(raw)
                lines.put(None)

            threading.Thread(target=pump, daemon=True).start()
            try:
                while True:
                    try:
                        raw = lines.get(timeout=0.5)
                    except queue.Empty:
                        report(None, None)  # raises Cancelled if the user pressed Cancel
                        continue
                    if raw is None:
                        break
                    line = _ANSI.sub("", raw).strip()
                    if line:
                        tail.append(line)
                        report(None, line[:300])
                rc = proc.wait()
            finally:
                if proc.poll() is None:  # cancelled or crashed mid-way
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            if rc != 0 or not os.path.exists(dst):
                raise RuntimeError("SeedVR2 failed:\n" + "\n".join(tail))
            with Image.open(dst) as im:
                return im.convert("RGB")
