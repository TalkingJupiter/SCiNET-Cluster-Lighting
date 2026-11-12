#!/usr/bin/env python3
"""Pretend to be the front end: send highlights to a running API.

For idle (chase) mode, where nothing else changes the racks. Works in meter
mode too; highlighted racks go back to their meter afterwards.

    .venv/bin/python scripts/simulate_highlights.py                     # random clicks
    .venv/bin/python scripts/simulate_highlights.py --pattern climb     # U1 -> U42 on every rack
    .venv/bin/python scripts/simulate_highlights.py --pattern sweep --racks Rack1,Rack2
    .venv/bin/python scripts/simulate_highlights.py --every 1 --count 20

Patterns:
    random  a random rack, 1-3 separate groups of 1-3 U's, like someone
            clicking machines in the front end (default)
    climb   the same U on every rack, one higher each step: a white dot
            climbing all racks together. Checks the U mapping everywhere
    sweep   a 3-U band moving up one rack, then the next rack

Each highlight holds for hold-seconds (5 by default), then the rack goes
back to idle on its own; a new highlight on the same rack replaces the old
one. Highlights need no token. Stop with Ctrl-C.
"""

import argparse
import random
import time

from simlib import Highlights, racks_to_use, send_highlights


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API address (default %(default)s)")
    p.add_argument("--racks", help="comma-separated rack names (default: every rack the API knows)")
    p.add_argument("--pattern", choices=Highlights.PATTERNS, default="random")
    p.add_argument("--every", type=float, default=3.0, help="seconds between highlights (default %(default)s)")
    p.add_argument("--count", type=int, default=0, help="stop after this many steps (default: run until Ctrl-C)")
    p.add_argument("--seed", type=int, help="repeat the same random sequence")
    args = p.parse_args()
    if args.every <= 0:
        p.error("--every must be greater than 0")

    base = args.base.rstrip("/")
    racks = racks_to_use(base, args.racks)
    plan = Highlights(racks, args.pattern, random.Random(args.seed))
    print(f"Sending {args.pattern} highlights to {len(racks)} racks every {args.every:g} s "
          f"via {base}. Ctrl-C to stop.\n")

    start = time.monotonic()
    steps = 0
    try:
        while True:
            results = send_highlights(base, plan.next())
            print(time.strftime("%H:%M:%S"), "  ".join(results))
            steps += 1
            if args.count and steps >= args.count:
                break
            time.sleep(max(0.0, start + steps * args.every - time.monotonic()))
    except KeyboardInterrupt:
        print("\nStopped. Highlighted racks go back to idle after hold-seconds.")


if __name__ == "__main__":
    main()
