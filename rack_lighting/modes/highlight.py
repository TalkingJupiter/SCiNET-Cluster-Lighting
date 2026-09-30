"""Highlight mode: breathe the requested U's; the rest of the rack is dark."""

from ..layout import run_range, to_strip, unit_runs
from .animate import segment


def unit_groups(cfg, rack, units):
    """Validate a request and group it into consecutive runs of U's."""
    runs = unit_runs(units, cfg.u_count)
    if not runs:
        raise ValueError("no units to highlight")

    needed = len(runs) * len(rack.sides)
    if needed > cfg.segments_per_rack:
        raise ValueError(
            f"{len(runs)} separate U groups on {len(rack.sides)} sides need "
            f"{needed} segments; {rack.name} has {cfg.segments_per_rack}. "
            f"At most {cfg.segments_per_rack // len(rack.sides)} groups."
        )
    return runs


def highlight_node(cfg, rack, effects, units):
    """Segments that highlight `units` (U numbers) on every side of `rack`.

    Consecutive U's share a segment; each group is drawn once per side,
    mirrored on sides that run downward. Pixels of this rack not covered by a
    segment are dark.
    """
    runs = unit_groups(cfg, rack, units)
    segments = []
    for first, last in runs:
        lo, hi = run_range(first, last, cfg.pattern, cfg.first_u_pixel)
        for side in rack.sides:
            start, stop = to_strip(side, lo, hi)
            segments.append(segment(start, stop, cfg.highlight, effects))
    return segments
