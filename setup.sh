#!/bin/bash
# Installs or repairs Engine: the Python environment, the SeedVR2 runner, and the
# model files. Safe to run again at any time - it only fills in what's missing.
#
#   ./setup.sh                      # everything (about 7.5 GB of models)
#   ./setup.sh --skip seedvr2-3b    # skip the big SeedVR2 download
set -euo pipefail
cd "$(dirname "$0")"

SEEDVR2_REPO="https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git"
SEEDVR2_COMMIT="4490bd1f482e026674543386bb2a4d176da245b9"   # v2.5.24, tested with Engine

PY=""
for c in python3.12 python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "Engine needs Python 3.12 or 3.13. Install it with:  brew install python@3.12"
  exit 1
fi

echo "==> Python environment (.venv) using $PY"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

echo "==> SeedVR2 runner (vendor/SeedVR2)"
mkdir -p vendor
if [ ! -d vendor/SeedVR2/.git ]; then
  git clone --quiet "$SEEDVR2_REPO" vendor/SeedVR2
fi
if ! git -C vendor/SeedVR2 cat-file -e "$SEEDVR2_COMMIT^{commit}" 2>/dev/null; then
  git -C vendor/SeedVR2 fetch --quiet origin
fi
git -C vendor/SeedVR2 checkout --quiet "$SEEDVR2_COMMIT"

echo "==> Model files"
PYTHONPATH="$PWD" PYTHONSAFEPATH=1 .venv/bin/python -m engine.download "$@"

chmod +x enhance Engine.app/Contents/MacOS/Engine 2>/dev/null || true
echo
echo "Done. Double-click Engine.app to start, or run:  ./enhance --help"
