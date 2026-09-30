"""Rack unit (U) to LED pixel mapping.

Two coordinate systems:
  rack  - pixels along one side, 0 = bottom. The same for every side.
  strip - the physical LED index on the controller.

U numbers become rack pixels using the repeating pattern (3, 3, 2): U1 = 3 px,
U2 = 3 px, U3 = 2 px, U4 = 3 px, ... Each side then puts rack pixels on
the strip, flipped if the side runs downward.

All ranges are half-open: (lo, hi) covers lo .. hi-1. WLED segments use the
same convention (stop is exclusive), so ranges go straight into the payload.
"""


def parse_units(text):
    """'1,2' / '5-8' / '1, 3-4' -> sorted unique U numbers."""
    units = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            if hi < lo:
                raise ValueError(f"backwards range {part!r}")
            units.update(range(lo, hi + 1))
        else:
            units.add(int(part))
    return sorted(units)


def unit_range(u, pattern, first_u_pixel=0):
    """Rack pixels (lo, hi) for a single U."""
    if u < 1:
        raise ValueError(f"U{u} is below U1")
    n = len(pattern)
    lo = first_u_pixel + sum(pattern[i % n] for i in range(u - 1))
    return lo, lo + pattern[(u - 1) % n]


def unit_runs(units, u_count):
    """Group U numbers into consecutive runs: [1,2,3,7] -> [(1,3), (7,7)].

    One WLED segment per run instead of one per U keeps the segment count
    down, and controllers only have 16-32 of them.
    """
    units = sorted(set(units))
    for u in units:
        if not 1 <= u <= u_count:
            raise ValueError(f"U{u} is outside 1..{u_count}")

    runs = []
    for u in units:
        if runs and u == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], u)
        else:
            runs.append((u, u))
    return runs


def run_range(first, last, pattern, first_u_pixel=0):
    """Rack pixels covering U `first` through U `last`."""
    lo, _ = unit_range(first, pattern, first_u_pixel)
    _, hi = unit_range(last, pattern, first_u_pixel)
    return lo, hi


def to_strip(side, lo, hi):
    """Rack pixels (lo, hi) on one side -> strip pixels (lo, hi)."""
    if not 0 <= lo < hi <= side.count:
        raise ValueError(f"rack pixels {lo}..{hi} outside {side.name} (0..{side.count})")
    if side.reverse:
        return side.start + side.count - hi, side.start + side.count - lo
    return side.start + lo, side.start + hi
