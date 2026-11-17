"""Command-line use:  ./enhance <image> [--model ID] [--scale N] [--out DIR]
                     ./enhance --list
"""

from __future__ import annotations

import argparse
import sys
import time

from .cards import CardError, load_cards


def _list_models() -> int:
    cards, problems = load_cards()
    print("Models (use the id with --model):\n")
    for c in cards:
        flag = " (default)" if c.default else ""
        state = "ready" if c.available else f"MISSING: {', '.join(c.missing_files)}"
        print(f"  {c.id:<22} {c.name}{flag}")
        print(f"  {'':<22} backend={c.backend}, default {c.default_scale:g}x, {state}")
        if c.best_for:
            print(f"  {'':<22} best for: {c.best_for}")
        print()
    for p in problems:
        print(f"  ! card problem: {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enhance", description="Enlarge and sharpen an image, privately, on this Mac.")
    ap.add_argument("image", nargs="*", help="image file(s) to enhance")
    ap.add_argument("-m", "--model", help="model id (see --list). Default: the model marked default")
    ap.add_argument("-s", "--scale", type=float, help="how much bigger, e.g. 2 or 4 (default: the model's default)")
    ap.add_argument("-o", "--out", help="folder for results (default: Engine/output)")
    ap.add_argument("-l", "--list", action="store_true", help="list available models")
    ap.add_argument("--open", action="store_true", help="open the result in Preview when done")
    args = ap.parse_args(argv)

    if args.list:
        return _list_models()
    if not args.image:
        ap.print_help()
        return 1

    from .core import Engine  # imported late so --list/--help are instant

    engine = Engine()
    last = {"t": 0.0}

    def report(frac, msg):
        now = time.time()
        if msg and (frac is None or frac >= 1 or now - last["t"] > 0.5):
            pct = f"{frac * 100:5.1f}% " if frac is not None else "       "
            print(f"  {pct}{msg}", flush=True)
            last["t"] = now

    status = 0
    for image in args.image:
        print(f"\n> {image}")
        try:
            r = engine.enhance(image, model=args.model, scale=args.scale, output_dir=args.out, report=report)
        except (CardError, FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"  Error: {e}", file=sys.stderr)
            status = 1
            continue
        print(f"\nDone in {r.seconds:g}s with {r.model_name}: "
              f"{r.input_size[0]}x{r.input_size[1]} -> {r.output_size[0]}x{r.output_size[1]}")
        print(r.output_path)
        if args.open:
            import subprocess
            subprocess.run(["open", r.output_path], check=False)
    return status


if __name__ == "__main__":
    sys.exit(main())
