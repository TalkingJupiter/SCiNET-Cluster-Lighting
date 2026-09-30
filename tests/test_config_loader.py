import os

import pytest

from rack_lighting import config_loader
from tests.conftest import BASE_INI


def test_loads(cfg):
    assert list(cfg.racks) == ["Rack1", "Rack2", "Rack3"]
    assert cfg.racks["Rack1"].redfish_ips == ("10.1.0.1", "10.1.0.2")
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


def test_chase_mode_needs_no_redfish_credentials(cfg):
    assert cfg.redfish_username is None


def test_meter_mode_needs_both_credentials(write_ini, monkeypatch):
    with pytest.raises(RuntimeError):
        write_ini(mode="meter")
    monkeypatch.setenv("redfish_username", "admin")
    with pytest.raises(RuntimeError):
        write_ini(mode="meter")
    monkeypatch.setenv("redfish_password", "x")
    assert write_ini(mode="meter").mode == "meter"


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
