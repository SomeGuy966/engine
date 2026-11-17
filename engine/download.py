"""Download the model files listed in the cards, and check them.

    .venv/bin/python -m engine.download                # everything that's missing
    .venv/bin/python -m engine.download ultrasharp     # just one model
    .venv/bin/python -m engine.download --skip seedvr2-3b
    .venv/bin/python -m engine.download --verify       # re-check files already on disk

Every file is checked against the SHA-256 written in its card, so a corrupted
or tampered download is rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys

from .cards import find_card, load_cards
from .paths import ensure_dirs


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.download")
    ap.add_argument("models", nargs="*", help="model ids (default: all)")
    ap.add_argument("--skip", default="", help="comma-separated model ids to skip")
    ap.add_argument("--verify", action="store_true", help="re-hash files that already exist")
    args = ap.parse_args(argv)

    ensure_dirs()
    cards, problems = load_cards()
    for p in problems:
        print("! card problem:", p)
    chosen = [find_card(m, cards) for m in args.models] if args.models else cards
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    failed = 0
    for card in chosen:
        if card.id in skip or not card.files:
            continue
        for f in card.files:
            dest = f.local
            if dest.exists() and not args.verify:
                print(f"  ok        {f.path}")
                continue
            if not dest.exists():
                if not f.url:
                    print(f"  MISSING   {f.path} (no download url in {card.id}.toml)")
                    failed += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".part")
                print(f"  download  {f.path}  <- {f.url}")
                rc = subprocess.run(["curl", "-fL", "--retry", "3", "-C", "-", "--progress-bar",
                                     "-o", str(part), f.url]).returncode
                if rc != 0:
                    print(f"  FAILED    {f.path} (curl exit {rc}; run again to resume)")
                    failed += 1
                    continue
                part.rename(dest)
            if f.sha256:
                print(f"  checking  {f.path} ...", end="", flush=True)
                got = sha256(dest)
                if got != f.sha256:
                    print(f" BAD CHECKSUM - deleting.\n            expected {f.sha256}\n            got      {got}")
                    dest.unlink()
                    failed += 1
                    continue
                print(" verified")
    print("\nAll model files ready." if not failed else f"\n{failed} file(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
