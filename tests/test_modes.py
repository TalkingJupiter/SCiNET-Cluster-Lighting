import pytest

from rack_lighting.modes.animate import default_animation, effect_id
from rack_lighting.modes.highlight import highlight_node, unit_groups
from tests.conftest import BASE_INI, EFFECTS


def spans(segments):
    return [(s["start"], s["stop"]) for s in segments]


# ---------------------------------------------------------------- effects

def test_effects_are_found_by_name():
    assert effect_id(EFFECTS, "Chase") == 28
    assert effect_id(EFFECTS, "breathe") == 2


def test_unknown_effect_is_an_error():
    with pytest.raises(ValueError, match="no effect named"):
        effect_id(EFFECTS, "Disco")


# ---------------------------------------------------------------- idle

def test_idle_runs_chase_on_both_sides(cfg):
    segs = default_animation(cfg, cfg.racks["Rack1"], EFFECTS)
    assert spans(segs) == [(0, 112), (114, 226)]
    assert all(s["fx"] == 28 and s["on"] for s in segs)


def test_idle_reverses_the_downward_side(cfg):
    a, b = default_animation(cfg, cfg.racks["Rack1"], EFFECTS)
    assert a["rev"] is False and b["rev"] is True


def test_idle_uses_configured_style(cfg):
    s = default_animation(cfg, cfg.racks["Rack1"], EFFECTS)[0]
    assert s["col"][0] == [255, 120, 0]
    assert (s["sx"], s["ix"], s["bri"]) == (160, 128, 255)


def test_idle_second_rack_on_a_shared_controller(cfg):
    segs = default_animation(cfg, cfg.racks["Rack2"], EFFECTS)
    assert spans(segs) == [(226, 338), (340, 452)]


def test_idle_with_one_side(write_ini):
    cfg = write_ini(BASE_INI.replace("side-b = 114, 112, down\n", "", 1))
    assert len(default_animation(cfg, cfg.racks["Rack1"], EFFECTS)) == 1


def test_segments_set_every_field(cfg):
    """Slots are reused across racks and modes, so nothing may be inherited."""
    fields = {"start", "stop", "on", "rev", "pal", "fx", "sx", "ix", "col", "bri"}
    for seg in default_animation(cfg, cfg.racks["Rack1"], EFFECTS):
        assert set(seg) == fields
    for seg in highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [1]):
        assert set(seg) == fields


# ---------------------------------------------------------------- highlight

def test_highlight_is_a_medium_fast_breathe(cfg):
    s = highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [1])[0]
    assert s["fx"] == 2
    assert s["sx"] == 200
    assert s["col"][0] == [255, 255, 255]
    assert s["rev"] is False


def test_highlight_u1_u2(cfg):
    segs = highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [1, 2])
    # U1+U2 = rack pixels 0..6 on side A, mirrored at the far end of side B
    assert spans(segs) == [(0, 6), (220, 226)]


def test_highlight_two_pixel_unit(cfg):
    segs = highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [3])
    assert spans(segs) == [(6, 8), (218, 220)]


def test_highlight_on_the_second_rack_of_a_controller(cfg):
    segs = highlight_node(cfg, cfg.racks["Rack2"], EFFECTS, [1, 2])
    assert spans(segs) == [(226, 232), (446, 452)]


def test_separate_units_get_separate_segments(cfg):
    segs = highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [1, 5])
    assert spans(segs) == [(0, 3), (223, 226), (11, 14), (212, 215)]


def test_whole_rack_is_one_segment_per_side(cfg):
    segs = highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, range(1, 43))
    assert spans(segs) == [(0, 112), (114, 226)]


def test_four_groups_fit_five_do_not(cfg):
    """8 segments per rack / 2 sides = 4 separate groups of U's."""
    rack = cfg.racks["Rack1"]
    assert len(highlight_node(cfg, rack, EFFECTS, [1, 3, 5, 7])) == 8
    with pytest.raises(ValueError, match="At most 4 groups"):
        highlight_node(cfg, rack, EFFECTS, [1, 3, 5, 7, 9])


def test_adjacent_units_count_as_one_group(cfg):
    assert len(unit_groups(cfg, cfg.racks["Rack1"], [1, 2, 3, 10, 11, 20, 30, 31, 32])) == 4


def test_highlight_nothing_is_an_error(cfg):
    with pytest.raises(ValueError):
        highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [])


def test_highlight_bad_unit(cfg):
    with pytest.raises(ValueError, match="outside"):
        highlight_node(cfg, cfg.racks["Rack1"], EFFECTS, [43])


# ---------------------------------------------------------------- the real racks

# Measured on Rack5 on 2026-11-11, in LEDs from the start of its strip:
# 259-LED strips; LED 1 is the bottom of U1 and LED 109 the top of U42 on
# side A; side B runs down 150-258.
MEASURED = {
    1: ((1, 4), (256, 259)),        # bottom: LED 1, and the strip's last LED
    42: ((108, 110), (150, 152)),   # top: LED 109, and side B's first
}
FIRST_RACKS = ["Rack1", "Rack3", "Rack5", "Rack7"]
SECOND_RACKS = ["Rack2", "Rack4", "Rack6", "Rack8"]


def strip_offset(cfg, rack):
    """Where this rack's strip starts on its controller (LED 0 is hidden, so
    side A starts one after it): 0 for output 1. For output 2 it is wherever
    WLED's output 2 starts: 300 while WLED is still set to 300 + 300, 259
    once it's changed to 259 + 259 (see the note in config.ini)."""
    return cfg.racks[rack].sides[0].start - 1


@pytest.mark.parametrize("rack", FIRST_RACKS + SECOND_RACKS)
@pytest.mark.parametrize("u", [1, 42])
def test_real_config_puts_u1_and_u42_where_measured(monkeypatch, rack, u):
    from rack_lighting import config_loader
    monkeypatch.setattr(config_loader, "load_dotenv", lambda: None)
    cfg = config_loader.load()
    off = strip_offset(cfg, rack)
    a, b = highlight_node(cfg, cfg.racks[rack], EFFECTS, [u])
    side_a, side_b = MEASURED[u]
    assert (a["start"] - off, a["stop"] - off) == side_a
    assert (b["start"] - off, b["stop"] - off) == side_b


def test_real_second_strip_starts_after_the_first(monkeypatch):
    """Output 2 can't start inside the first strip's 259 LEDs."""
    from rack_lighting import config_loader
    monkeypatch.setattr(config_loader, "load_dotenv", lambda: None)
    cfg = config_loader.load()
    for rack in SECOND_RACKS:
        assert strip_offset(cfg, rack) >= 259
