"""Where everything lives. All paths are relative to the Engine folder."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODELS_DIR = ROOT / "models"          # model cards (*.toml) - the "wardrobe"
WEIGHTS_DIR = MODELS_DIR / "weights"  # the actual model files (big, not in git)
OUTPUT_DIR = ROOT / "output"          # enhanced images land here
UPLOADS_DIR = ROOT / "uploads"        # images dropped/pasted into the app
LOGS_DIR = ROOT / "logs"
VENDOR_DIR = ROOT / "vendor"          # third-party code (SeedVR2 runner)
WEB_DIR = Path(__file__).resolve().parent / "web"
PYTHON = ROOT / ".venv" / "bin" / "python"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def ensure_dirs() -> None:
    for d in (WEIGHTS_DIR, OUTPUT_DIR, UPLOADS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
