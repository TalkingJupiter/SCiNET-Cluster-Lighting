import pytest

from layout import parse_units, run_range, to_strip, unit_range, unit_runs
from config_loader import Side

PATTERN = (3, 3, 2)


# ---------------------------------------------------------------- parse_units

@pytest.mark.parametrize("text, expected", [
    ("1,2", [1, 2]),
    ("2,1,2", [1, 2]),
    (" 1 , 3 ", [1, 3]),
    ("5-8", [5, 6, 7, 8]),
    ("1,3-4,10", [1, 3, 4, 10]),
    ("7", [7]),
    ("", []),
])
def test_parse_units(text, expected):
    assert parse_units(text) == expected


@pytest.mark.parametrize("text", ["8-5", "a", "1,,x"])
def test_parse_units_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_units(text)


# ---------------------------------------------------------------- the 3,3,2 pattern

def test_first_units_follow_3_3_2():
    assert unit_range(1, PATTERN) == (0, 3)
    assert unit_range(2, PATTERN) == (3, 6)
    assert unit_range(3, PATTERN) == (6, 8)      # every third U loses a pixel
    assert unit_range(4, PATTERN) == (8, 11)


def test_units_tile_with_no_gaps_or_overlaps():
    for u in range(1, 42):
        assert unit_range(u, PATTERN)[1] == unit_range(u + 1, PATTERN)[0]


def test_42_units_use_112_pixels():
    assert unit_range(42, PATTERN)[1] == 112


def test_top_unit():
    assert unit_range(42, PATTERN) == (110, 112)  # U42 is a 2-pixel U


def test_first_u_pixel_offsets_everything():
    assert unit_range(1, PATTERN, first_u_pixel=1) == (1, 4)
    assert unit_range(3, PATTERN, first_u_pixel=1) == (7, 9)


def test_u0_is_rejected():
    with pytest.raises(ValueError):
        unit_range(0, PATTERN)


# ---------------------------------------------------------------- runs

def test_consecutive_units_merge():
    assert unit_runs([1, 2], 42) == [(1, 2)]
    assert unit_runs([3, 1, 2, 7, 9, 8], 42) == [(1, 3), (7, 9)]


def test_separate_units_stay_separate():
    assert unit_runs([1, 3], 42) == [(1, 1), (3, 3)]


def test_run_range_spans_the_whole_run():
    assert run_range(1, 2, PATTERN) == (0, 6)
    assert run_range(3, 4, PATTERN) == (6, 11)


@pytest.mark.parametrize("units", [[0], [43], [1, 43]])
def test_units_outside_the_rack_are_rejected(units):
    with pytest.raises(ValueError):
        unit_runs(units, 42)


# ---------------------------------------------------------------- sides

UP = Side("side-a", 0, 113, False)
DOWN = Side("side-b", 113, 113, True)


def test_upward_side_is_an_offset():
    assert to_strip(UP, 0, 3) == (0, 3)
    assert to_strip(Side("s", 10, 113, False), 0, 3) == (10, 13)


def test_downward_side_is_mirrored():
    # U1 is the bottom of the rack, which is the far end of a downward side.
    assert to_strip(DOWN, 0, 3) == (223, 226)
    assert to_strip(DOWN, 3, 6) == (220, 223)


def test_mirror_keeps_the_same_width():
    for lo, hi in [(0, 3), (6, 8), (110, 112)]:
        a = to_strip(UP, lo, hi)
        b = to_strip(DOWN, lo, hi)
        assert a[1] - a[0] == b[1] - b[0] == hi - lo


def test_uncut_strip_with_gap_over_the_top():
    over_the_top = Side("side-b", 149, 113, True)
    assert to_strip(over_the_top, 0, 3) == (259, 262)


def test_range_outside_the_side_is_rejected():
    with pytest.raises(ValueError):
        to_strip(UP, 110, 114)
