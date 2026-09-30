import pytest

from modes.animate import default_animation, effect_id
from modes.highlight import highlight_node, unit_groups
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
    assert spans(segs) == [(0, 113), (113, 226)]
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
    assert spans(segs) == [(226, 339), (339, 452)]


def test_idle_with_one_side(write_ini):
    cfg = write_ini(BASE_INI.replace("side-b = 113, 113, down\n", "", 1))
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
