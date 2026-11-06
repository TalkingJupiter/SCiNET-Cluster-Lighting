"""kW meter mode: a power reading becomes a bar of segments.

Test config: min 0, amber from 30, red from 40, max 50 kW over 112 pixels,
so amber starts at pixel 67 and red at pixel 90. Rack1's side A runs up
over strip pixels 0-113, side B runs down over 113-226.
"""

from datetime import datetime, timezone

import pytest

from rack_lighting.modes.kw_meter import kw_meter
from rack_lighting.power import Reading
from tests.conftest import EFFECTS

GREEN, AMBER, RED = [0, 200, 0], [255, 140, 0], [255, 0, 0]
SOLID, BLINK = 0, 1


def reading(kw):
    return Reading(kw=kw, measured_at=datetime(2026, 11, 5, tzinfo=timezone.utc), received_at=0)


def meter(cfg, kw, rack="Rack1"):
    r = kw if kw is None else reading(kw)
    return kw_meter(cfg, cfg.racks[rack], EFFECTS, r)


def spans(segments):
    return [(s["start"], s["stop"]) for s in segments]


def colours(segments):
    return [s["col"][0] for s in segments]


def lit(segments):
    """Pixels lit on side A (the first segment of each pair)."""
    return sum(s["stop"] - s["start"] for s in segments[::2])


# ---------------------------------------------------------------- the bar

def test_zero_kw_is_dark(cfg):
    """0 kW is a real reading, and must not look like no data."""
    assert meter(cfg, 0) == []


def test_below_amber_is_green_only(cfg):
    segs = meter(cfg, 25)                       # 25/50 × 112 = 56 pixels
    assert spans(segs) == [(0, 56), (170, 226)]
    assert colours(segs) == [GREEN, GREEN]


def test_between_thresholds_is_green_then_amber(cfg):
    segs = meter(cfg, 35)                       # 78 pixels
    assert spans(segs) == [(0, 67), (159, 226), (67, 78), (148, 159)]
    assert colours(segs) == [GREEN, GREEN, AMBER, AMBER]


def test_full_scale_is_all_three_zones(cfg):
    segs = meter(cfg, 50)
    assert spans(segs) == [
        (0, 67), (159, 226),                    # green
        (67, 90), (136, 159),                   # amber
        (90, 112), (114, 136),                  # red
    ]
    assert colours(segs) == [GREEN, GREEN, AMBER, AMBER, RED, RED]


def test_exactly_at_amber_has_no_amber_yet(cfg):
    """No empty zones: a zone the bar hasn't entered sends no segment."""
    assert colours(meter(cfg, 30)) == [GREEN, GREEN]


def test_exactly_at_red_has_no_red_yet(cfg):
    assert colours(meter(cfg, 40)) == [GREEN, GREEN, AMBER, AMBER]


def test_above_max_is_a_full_bar_not_taller(cfg):
    assert meter(cfg, 60) == meter(cfg, 50)


def test_below_min_is_dark(cfg):
    assert meter(cfg, -5) == []


@pytest.mark.parametrize("kw, pixels", [
    (24.6, 55),     # 55.1: rounding kW to 25 first would give 56
    (0.3, 1),       # 0.67: rounding kW to 0 first would give a dark rack
    (12.4, 28),     # 27.8
])
def test_decimal_readings_round_once_at_the_end(cfg, kw, pixels):
    assert lit(meter(cfg, kw)) == pixels


def test_scale_starts_at_min_kw(write_ini):
    """With min 10, max 50: 30 kW is halfway, 56 pixels, and 10 kW is dark."""
    cfg = write_ini(min_kw=10)
    assert lit(meter(cfg, 30)) == 56
    assert meter(cfg, 10) == []


# ---------------------------------------------------------------- sides

def test_both_sides_light_the_same_height(cfg):
    for kw in (5, 25, 35, 45, 50):
        segs = meter(cfg, kw)
        for a, b in zip(segs[::2], segs[1::2]):
            assert a["stop"] - a["start"] == b["stop"] - b["start"]


def test_downward_side_is_mirrored(cfg):
    """Side B runs down, so its bottom pixels are at the end of its range."""
    _, b = meter(cfg, 25)
    assert b["stop"] == 226


def test_second_rack_on_a_controller_uses_its_own_pixels(cfg):
    assert spans(meter(cfg, 25, rack="Rack2")) == [(226, 282), (396, 452)]


def test_never_more_than_six_segments(cfg):
    for tenths in range(-50, 700, 5):
        assert len(meter(cfg, tenths / 10)) <= 6
    assert 6 <= cfg.segments_per_rack


# ---------------------------------------------------------------- style

def test_zones_are_solid_at_meter_brightness(cfg):
    for s in meter(cfg, 50):
        assert s["fx"] == SOLID
        assert s["bri"] == 200
        assert s["on"] is True


def test_zone_colours_come_from_the_config(write_ini):
    cfg = write_ini(green="1, 2, 3", amber="4, 5, 6", red="7, 8, 9")
    assert colours(meter(cfg, 50)) == [[1, 2, 3]] * 2 + [[4, 5, 6]] * 2 + [[7, 8, 9]] * 2


# ---------------------------------------------------------------- no data

@pytest.mark.parametrize("kw", [None, "kw-none"], ids=["no-reading", "kw-none"])
def test_no_data_blinks_red_over_the_whole_bar(cfg, kw):
    """No reading at all (never sent, or stale) and DevOps saying kw=null
    look the same: the whole column blinking red."""
    r = None if kw is None else reading(None)
    segs = kw_meter(cfg, cfg.racks["Rack1"], EFFECTS, r)
    assert spans(segs) == [(0, 112), (114, 226)]
    assert colours(segs) == [RED, RED]
    assert all(s["fx"] == BLINK for s in segs)


def test_no_data_differs_from_zero_and_from_full(cfg):
    assert meter(cfg, None) != meter(cfg, 0)
    assert meter(cfg, None) != meter(cfg, 50)
