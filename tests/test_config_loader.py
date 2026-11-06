import os

import pytest

from rack_lighting import config_loader
from tests.conftest import BASE_INI


def test_loads(cfg):
    assert list(cfg.racks) == ["Rack1", "Rack2", "Rack3"]
    assert cfg.mode == "chase"
    assert cfg.pattern == (3, 3, 2)
    assert cfg.idle.effect == "Chase"
    assert cfg.highlight.effect == "Breathe"
    assert cfg.highlight.speed == 200
    assert cfg.segments_per_rack == 8
    assert cfg.highlight_hold_s == 5


def test_hold_must_be_positive(write_ini):
    with pytest.raises(ValueError, match="hold-seconds"):
        write_ini(hold_seconds="0")


def test_sides_belong_to_each_rack(cfg):
    a, b = cfg.racks["Rack1"].sides
    assert (a.start, a.count, a.reverse) == (0, 113, False)
    assert (b.start, b.stop, b.reverse) == (113, 226, True)
    assert cfg.racks["Rack2"].sides[0].start == 226


def test_racks_grouped_by_controller(cfg):
    assert cfg.controllers == {"10.0.0.1": ("Rack1", "Rack2"), "10.0.0.3": ("Rack3",)}


def test_racks_on_one_controller_must_not_overlap(write_ini):
    bad = BASE_INI.replace("side-a = 226, 113, up", "side-a = 200, 113, up")
    with pytest.raises(ValueError, match="overlap on controller 10.0.0.1"):
        write_ini(bad)


def test_same_pixels_on_different_controllers_is_fine(cfg):
    assert cfg.racks["Rack1"].sides[0].start == cfg.racks["Rack3"].sides[0].start


def test_segment_budget_must_fit_the_controller(write_ini):
    with pytest.raises(ValueError, match="2 racks x 9"):
        write_ini(segments_per_rack="9")


def test_three_racks_on_one_controller_do_not_fit(write_ini):
    three = BASE_INI.replace("led-ip = 10.0.0.3", "led-ip = 10.0.0.1").replace(
        "side-a = 0, 113, up\nside-b = 113, 113, down\n\n[Led-Controller]",
        "side-a = 452, 113, up\nside-b = 565, 113, down\n\n[Led-Controller]")
    with pytest.raises(ValueError, match="3 racks x 8"):
        write_ini(three)


def test_rack_without_sides(write_ini):
    bad = BASE_INI.replace("side-a = 0, 113, up\nside-b = 113, 113, down\n", "", 1)
    with pytest.raises(ValueError, match="Rack1 needs at least one side"):
        write_ini(bad)


def test_loads_without_power_token(cfg):
    """No token configured is allowed; the power endpoint then rejects everything."""
    assert cfg.power_ingest_token is None


def test_stale_after_defaults_to_30_seconds(write_ini):
    assert write_ini(BASE_INI.replace("stale-after-seconds = 30\n", "")).stale_after_seconds == 30


def test_stale_after_accepts_fractions(write_ini):
    # [Energy] is the last section in BASE_INI, so appending lands inside it.
    assert write_ini(stale_after_seconds="7.5").stale_after_seconds == 7.5


@pytest.mark.parametrize("value", ["0", "-5"])
def test_stale_after_must_be_positive(write_ini, value):
    with pytest.raises(ValueError, match="stale-after-seconds"):
        write_ini(stale_after_seconds=value)


def test_power_token_is_read_from_the_environment(write_ini, monkeypatch):
    monkeypatch.setenv("power_ingest_token", "s3cret")
    assert write_ini().power_ingest_token == "s3cret"


def test_unknown_mode(write_ini):
    with pytest.raises(ValueError, match="mode"):
        write_ini(mode="disco")


def test_bad_direction(write_ini):
    with pytest.raises(ValueError, match="direction"):
        write_ini(side_b="113, 113, sideways")


def test_overlapping_sides(write_ini):
    with pytest.raises(ValueError, match="overlap"):
        write_ini(side_b="100, 113, down")


def test_side_too_short_for_the_units(write_ini):
    with pytest.raises(ValueError, match="needs 112"):
        write_ini(side_a="0, 111, up")


def test_first_u_pixel_counts_against_side_length(write_ini):
    write_ini(first_u_pixel="1")          # 113 = 1 + 112, fits exactly
    with pytest.raises(ValueError, match="needs 114"):
        write_ini(first_u_pixel="2")


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        config_loader.load("/nonexistent/config.ini")


def test_real_config_file_loads(monkeypatch):
    """The config.ini in the repo must always be loadable."""
    monkeypatch.setattr(config_loader, "load_dotenv", lambda: None)
    cfg = config_loader.load()
    assert len(cfg.racks) == 8
    assert cfg.u_count == 42


# ---------------------------------------------------------------- kW meter

def test_meter_scale_and_thresholds_are_read(cfg):
    assert (cfg.min_kw, cfg.amber_from_kw, cfg.red_from_kw, cfg.max_kw) == (0, 30, 40, 50)



def test_meter_zones_are_still_bars(cfg):
    for zone, colour in [
        (cfg.meter.green, (0, 200, 0)),
        (cfg.meter.amber, (255, 140, 0)),
        (cfg.meter.red, (255, 0, 0)),
    ]:
        assert zone.effect == "Solid"
        assert zone.color == colour
        assert zone.brightness == 200


def test_no_data_blinks_in_the_meters_red(cfg):
    assert cfg.meter.no_data.effect == "Blink"
    assert cfg.meter.no_data.color == cfg.meter.red.color
    assert cfg.meter.no_data.brightness == 200


def test_no_data_follows_a_changed_red(write_ini):
    """One colour setting: change red and "no data" changes with it."""
    cfg = write_ini(red="200, 0, 50")
    assert cfg.meter.red.color == cfg.meter.no_data.color == (200, 0, 50)


def test_no_data_speed_defaults_to_128(cfg):
    assert cfg.meter.no_data.speed == 128


def test_no_data_speed_is_configurable(write_ini):
    text = BASE_INI.replace("no-data-effect = Blink", "no-data-effect = Blink\nno-data-speed = 60")
    assert write_ini(text).meter.no_data.speed == 60


@pytest.mark.parametrize("values, key", [
    # The scale must run upwards.
    ({"min_kw": "50"}, "min-kw"),                           # min == max
    ({"min_kw": "60"}, "min-kw"),                           # min > max
    # Amber must start below red.
    ({"amber_from_kw": "40"}, "amber-from-kw"),             # amber == red
    ({"amber_from_kw": "45"}, "amber-from-kw"),             # amber > red
    # Both thresholds must sit inside the scale.
    ({"amber_from_kw": "-5"}, "amber-from-kw"),             # below min: 0 kW would show amber
    ({"amber_from_kw": "0"}, "amber-from-kw"),              # at min: same
    ({"min_kw": "10", "amber_from_kw": "5"}, "amber-from-kw"),   # below a non-zero min
    ({"red_from_kw": "50"}, "red-from-kw"),                 # at max: red could never show
    ({"red_from_kw": "80"}, "red-from-kw"),                 # above max: same
], ids=[
    "min-equals-max", "min-above-max",
    "amber-equals-red", "amber-above-red",
    "amber-below-min", "amber-at-min", "amber-below-nonzero-min",
    "red-at-max", "red-above-max",
])
def test_meter_scale_must_make_sense(write_ini, values, key):
    with pytest.raises(ValueError, match=key):
        write_ini(**values)
