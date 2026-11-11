"""kW meter mode: a bar from the bottom, coloured by thresholds."""

from ..layout import run_range, to_strip
from .animate import segment


def kw_meter(cfg, rack, effects, reading):
    """Segments for the kW meter on one rack.

    reading is a power.Reading, or None when there is no current reading.
    """
    def to_pixels(kw):
        level = (kw - cfg.min_kw) / (cfg.max_kw - cfg.min_kw)
        return max(0, min(round(level * height), height))

    bar_lo, bar_hi = run_range(1, cfg.u_count, cfg.u_count, rack.sides[0].count)
    height = bar_hi - bar_lo
    segments = []
    if reading is None or reading.kw is None:
        for side in rack.sides:
            start, stop = to_strip(side, bar_lo, bar_hi)
            segments.append(segment(start, stop, cfg.meter.no_data, effects))

        return segments

    top = bar_lo + to_pixels(reading.kw)
    amber_at = bar_lo + to_pixels(cfg.amber_from_kw)
    red_at = bar_lo + to_pixels(cfg.red_from_kw)

    zones = [
        (bar_lo, min(top, amber_at), cfg.meter.green),
        (amber_at, min(top, red_at), cfg.meter.amber),
        (red_at, top, cfg.meter.red),
    ]

    for lo, hi, style in zones:
        if lo >= hi:
            continue
        for side in rack.sides:
            start, stop = to_strip(side, lo, hi)
            segments.append(segment(start, stop, style, effects))

    return segments
