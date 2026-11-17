"""Command-line use:  ./enhance <image> [--model ID] [--scale N] [--out DIR]
                     ./enhance <image> --model ID1,ID2,...   (compare several models)
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
    ap.add_argument("-m", "--model", action="append",
                    help="model id (see --list). Several: -m a,b or -m a -m b (also saves a comparison image). "
                         "Default: the model marked default")
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

    models = [m.strip() for group in (args.model or []) for m in group.split(",") if m.strip()]
    status = 0
    for image in args.image:
        print(f"\n> {image}")
        try:
            if len(models) > 1:
                multi = engine.enhance_many(image, models, scale=args.scale, output_dir=args.out, report=report)
                results, to_open = multi.results, multi.comparison_path
            else:
                r = engine.enhance(image, model=models[0] if models else None, scale=args.scale,
                                   output_dir=args.out, report=report)
                results, to_open, multi = [r], r.output_path, None
        except (CardError, FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"  Error: {e}", file=sys.stderr)
            status = 1
            continue
        for r in results:
            print(f"\nDone in {r.seconds:g}s with {r.model_name}: "
                  f"{r.input_size[0]}x{r.input_size[1]} -> {r.output_size[0]}x{r.output_size[1]}")
            print(r.output_path)
        if multi:
            for e in multi.errors:
                print(f"\n  {e['model_name']} failed: {e['error']}", file=sys.stderr)
                status = 1
            if multi.comparison_path:
                print(f"\nComparison image ({len(multi.results)} models, {multi.seconds:g}s total):")
                print(multi.comparison_path)
        if args.open and to_open:
            import subprocess
            subprocess.run(["open", to_open], check=False)
    return status


if __name__ == "__main__":
    sys.exit(main())
