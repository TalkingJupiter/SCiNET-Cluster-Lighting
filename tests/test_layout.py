import pytest

from rack_lighting.layout import parse_units, run_range, to_strip, unit_range, unit_runs
from rack_lighting.config_loader import Side



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


# ---------------------------------------------------------------- spreading U's

def sizes(length, u_count=42):
    return [hi - lo for lo, hi in (unit_range(u, u_count, length) for u in range(1, u_count + 1))]


def test_112_pixels_give_the_old_3_3_2_pattern():
    assert unit_range(1, 42, 112) == (0, 3)
    assert unit_range(2, 42, 112) == (3, 6)
    assert unit_range(3, 42, 112) == (6, 8)
    assert unit_range(4, 42, 112) == (8, 11)
    assert sizes(112) == [3, 3, 2] * 14


def test_real_109_pixel_sides():
    """Measured on Rack5: LED 1 is the bottom of U1, LED 109 the top of U42."""
    assert unit_range(1, 42, 109) == (0, 3)
    assert unit_range(42, 42, 109) == (107, 109)
    assert set(sizes(109)) == {2, 3}
    assert sizes(109).count(3) == 25


@pytest.mark.parametrize("length", [42, 100, 109, 112, 113, 200])
def test_units_tile_the_whole_side(length):
    """No gaps, no overlaps, U1 at the bottom and U42 at the very top."""
    assert unit_range(1, 42, length)[0] == 0
    for u in range(1, 42):
        assert unit_range(u, 42, length)[1] == unit_range(u + 1, 42, length)[0]
    assert unit_range(42, 42, length)[1] == length


@pytest.mark.parametrize("length", [109, 112, 113])
def test_units_differ_by_at_most_one_pixel(length):
    """Evenly spread: never a 4 next to a 2."""
    assert max(sizes(length)) - min(sizes(length)) <= 1


def test_one_pixel_per_unit_at_minimum():
    assert sizes(42) == [1] * 42


@pytest.mark.parametrize("u", [0, 43])
def test_units_outside_the_rack_are_rejected_by_unit_range(u):
    with pytest.raises(ValueError):
        unit_range(u, 42, 112)


# ---------------------------------------------------------------- runs

def test_consecutive_units_merge():
    assert unit_runs([1, 2], 42) == [(1, 2)]
    assert unit_runs([3, 1, 2, 7, 9, 8], 42) == [(1, 3), (7, 9)]


def test_separate_units_stay_separate():
    assert unit_runs([1, 3], 42) == [(1, 1), (3, 3)]


def test_run_range_spans_the_whole_run():
    assert run_range(1, 2, 42, 112) == (0, 6)
    assert run_range(3, 4, 42, 112) == (6, 11)
    assert run_range(1, 42, 42, 109) == (0, 109)


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
