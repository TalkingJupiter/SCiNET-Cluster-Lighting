#!/usr/bin/env python3
"""Pretend to be DevOps: push changing kW readings to a running API.

    .venv/bin/python scripts/simulate_power.py                      # wave on every rack
    .venv/bin/python scripts/simulate_power.py --pattern sweep      # all bars 0 -> max -> 0
    .venv/bin/python scripts/simulate_power.py --racks Rack1,Rack2 --pattern random
    .venv/bin/python scripts/simulate_power.py --pattern steady --kw 35
    .venv/bin/python scripts/simulate_power.py --highlights random  # plus front-end clicks
    .venv/bin/python scripts/simulate_power.py --base http://10.0.0.2:8000

Patterns:
    wave    every rack rises and falls, each a little behind the one before,
            so the bars ripple across the room (default)
    sweep   every rack together, 0 -> max -> 0 over --period seconds
    random  each rack wanders up and down on its own
    steady  every rack at --kw

--highlights random|climb|sweep also sends highlights every --highlight-every
seconds, the same patterns as scripts/simulate_highlights.py: a highlighted
rack breathes white for hold-seconds, then goes back to its meter.

The meter only shows readings when the server runs with `mode = meter`.
Stop with Ctrl-C: the racks go back to blinking red (no data) once the last
reading is older than stale-after-seconds (30 by default).

The token is read from .env exactly as the server reads it, and never
printed.
"""

import argparse
import math
import random
import sys
import time
from datetime import datetime, timezone

from simlib import Highlights, detail, racks_to_use, read_token, request, send_highlights


def scale_from_config():
    """(min_kw, max_kw) from config.ini, so the values fill the meter's scale."""
    try:
        from rack_lighting import config_loader
        cfg = config_loader.load()
        return cfg.min_kw, cfg.max_kw
    except Exception:
        return 0, 50


class Patterns:
    """kW for each rack at time t (seconds since start)."""

    def __init__(self, racks, lo, hi, period, kw):
        self.racks, self.lo, self.hi, self.period, self.kw = racks, lo, hi, period, kw
        self.walk = {r: random.uniform(lo, hi) for r in racks}

    def wave(self, t):
        n = len(self.racks)
        return {
            r: self.lo + (self.hi - self.lo) * (1 + math.sin(2 * math.pi * (t / self.period - i / n))) / 2
            for i, r in enumerate(self.racks)
        }

    def sweep(self, t):
        phase = (t % self.period) / self.period              # 0..1
        level = 1 - abs(2 * phase - 1)                        # 0 -> 1 -> 0
        return {r: self.lo + (self.hi - self.lo) * level for r in self.racks}

    def random(self, t):
        step = (self.hi - self.lo) / 8
        for r in self.racks:
            self.walk[r] = min(self.hi, max(self.lo, self.walk[r] + random.uniform(-step, step)))
        return dict(self.walk)

    def steady(self, t):
        return {r: self.kw for r in self.racks}


def push_round(base, token, values):
    """PUT one reading per rack. Returns (printable cells, problems)."""
    measured_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cells, problems = [], []
    for rack, kw in values.items():
        kw = round(kw, 1)
        code, body = request("PUT", f"{base}/racks/{rack}/power",
                             {"kw": kw, "measured_at": measured_at}, token)
        cells.append(f"{rack} {kw:5.1f}")
        if code != 204:
            problems.append(f"{rack}: {code or 'no answer'} {detail(body) or ''}".strip())
    return cells, problems


def main():
    lo_cfg, hi_cfg = scale_from_config()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API address (default %(default)s)")
    p.add_argument("--racks", help="comma-separated rack names (default: every rack the API knows)")
    p.add_argument("--pattern", choices=["wave", "sweep", "random", "steady"], default="wave")
    p.add_argument("--interval", type=float, default=2.0, help="seconds between pushes (default %(default)s)")
    p.add_argument("--period", type=float, default=40.0, help="seconds per wave or sweep (default %(default)s)")
    p.add_argument("--min", type=float, default=lo_cfg, dest="lo", help="lowest kW (default: min-kw, %(default)s)")
    p.add_argument("--max", type=float, default=hi_cfg, dest="hi", help="highest kW (default: max-kw, %(default)s)")
    p.add_argument("--kw", type=float, default=35.0, help="value for --pattern steady (default %(default)s)")
    p.add_argument("--highlights", choices=Highlights.PATTERNS,
                   help="also send highlights in this pattern (default: none)")
    p.add_argument("--highlight-every", type=float, default=6.0,
                   help="seconds between highlights with --highlights (default %(default)s)")
    p.add_argument("--count", type=int, default=0, help="stop after this many rounds (default: run until Ctrl-C)")
    p.add_argument("--seed", type=int, help="repeat the same random sequence")
    args = p.parse_args()

    if args.interval <= 0 or args.period <= 0 or args.highlight_every <= 0:
        p.error("--interval, --period and --highlight-every must be greater than 0")
    if args.lo < 0 or args.hi < args.lo:
        p.error("need 0 <= --min <= --max")

    random.seed(args.seed)
    base = args.base.rstrip("/")
    token = read_token()
    if not token:
        sys.exit("No power_ingest_token in .env: the API would reject every push (401).")
    racks = racks_to_use(base, args.racks)

    pattern = getattr(Patterns(racks, args.lo, args.hi, args.period, args.kw), args.pattern)
    highlights = Highlights(racks, args.highlights, random.Random(args.seed)) if args.highlights else None
    extra = f", plus {args.highlights} highlights every {args.highlight_every:g} s" if highlights else ""
    print(f"Pushing a {args.pattern} pattern ({args.lo:g}-{args.hi:g} kW) to {len(racks)} racks "
          f"every {args.interval:g} s{extra} via {base}. Ctrl-C to stop.\n")

    start = time.monotonic()
    next_highlight = start
    rounds = 0
    try:
        while True:
            cells, problems = push_round(base, token, pattern(time.monotonic() - start))
            print(time.strftime("%H:%M:%S"), "  ".join(cells))
            for problem in problems:
                print("   !", problem)
            if highlights and time.monotonic() >= next_highlight:
                print("   highlight:", "  ".join(send_highlights(base, highlights.next())))
                next_highlight += args.highlight_every

            rounds += 1
            if args.count and rounds >= args.count:
                break
            # Sleep to the next round on the clock, so slow pushes don't drift.
            time.sleep(max(0.0, start + rounds * args.interval - time.monotonic()))
    except KeyboardInterrupt:
        print("\nStopped. The racks blink red once the last readings go stale.")


if __name__ == "__main__":
    main()
