import pytest

from rack_lights import RackLights, controller_state
from tests.conftest import FakeClient


@pytest.fixture
def lights(cfg):
    return RackLights(cfg, client_factory=FakeClient)


def last(lights, ip):
    return lights.clients[ip].states[-1]


def live(state):
    return [s for s in state["seg"] if s.get("stop") != 0]


def spans(state):
    return [(s["start"], s["stop"], s["fx"]) for s in live(state)]


CHASE, BREATHE = 28, 2


# ---------------------------------------------------------------- numbering

def test_controller_state_numbers_from_zero_and_clears_the_rest():
    state = controller_state([[{"a": 1}], [{"b": 2}, {"c": 3}]], 6)
    assert state["seg"] == [
        {"id": 0, "a": 1}, {"id": 1, "b": 2}, {"id": 2, "c": 3},
        {"id": 3, "stop": 0}, {"id": 4, "stop": 0}, {"id": 5, "stop": 0},
    ]


def test_controller_state_over_the_limit():
    with pytest.raises(ValueError):
        controller_state([[{}] * 5], 4)


# ---------------------------------------------------------------- controllers

def test_one_client_per_controller_not_per_rack(lights):
    assert sorted(lights.clients) == ["10.0.0.1", "10.0.0.3"]


def test_idle_all_writes_each_controller_once(lights):
    lights.idle_all()
    assert len(lights.clients["10.0.0.1"].states) == 1
    assert len(lights.clients["10.0.0.3"].states) == 1


def test_idle_shared_controller_chases_both_racks(lights):
    lights.idle_all()
    assert spans(last(lights, "10.0.0.1")) == [
        (0, 113, CHASE), (113, 226, CHASE),       # Rack1
        (226, 339, CHASE), (339, 452, CHASE),     # Rack2
    ]


# ---------------------------------------------------------------- highlight

def test_highlight_keeps_the_neighbour_chasing(lights):
    lights.highlight("Rack1", [1, 2])
    assert spans(last(lights, "10.0.0.1")) == [
        (0, 6, BREATHE), (220, 226, BREATHE),     # Rack1: U1-U2 only
        (226, 339, CHASE), (339, 452, CHASE),     # Rack2 untouched
    ]


def test_both_racks_on_one_controller_highlighted(lights):
    lights.highlight("Rack1", [1, 2])
    lights.highlight("Rack2", [3])
    assert spans(last(lights, "10.0.0.1")) == [
        (0, 6, BREATHE), (220, 226, BREATHE),
        (232, 234, BREATHE), (444, 446, BREATHE),
    ]


def test_clearing_one_rack_leaves_the_other_highlighted(lights):
    lights.highlight("Rack1", [1, 2])
    lights.highlight("Rack2", [3])
    lights.idle("Rack1")
    assert spans(last(lights, "10.0.0.1")) == [
        (0, 113, CHASE), (113, 226, CHASE),
        (232, 234, BREATHE), (444, 446, BREATHE),
    ]


def test_ids_are_always_contiguous_from_zero(lights):
    """WLED packs segments; a gap would shift the next rack's IDs."""
    for rack, units in [("Rack1", [1, 3, 5, 7]), ("Rack2", [1]), ("Rack1", [])]:
        lights.highlight(rack, units)
        state = last(lights, "10.0.0.1")
        ids = [s["id"] for s in state["seg"]]
        assert ids == list(range(16))
        n = len(live(state))
        assert all(s == {"id": s["id"], "stop": 0} for s in state["seg"][n:])


def test_both_racks_at_full_budget_fill_the_controller(lights):
    lights.highlight("Rack1", [1, 3, 5, 7])
    lights.highlight("Rack2", [2, 4, 6, 8])
    assert len(live(last(lights, "10.0.0.1"))) == 16


def test_other_controllers_are_not_written(lights):
    lights.highlight("Rack1", [1])
    assert lights.clients["10.0.0.3"].states == []


def test_empty_selection_goes_back_to_idle(lights):
    lights.highlight("Rack3", [4])
    lights.highlight("Rack3", [])
    assert spans(last(lights, "10.0.0.3")) == [(0, 113, CHASE), (113, 226, CHASE)]


def test_unknown_rack(lights):
    with pytest.raises(KeyError, match="unknown rack"):
        lights.highlight("Rack9", [1])


def test_bad_request_writes_nothing(lights):
    for units in ([99], [1, 3, 5, 7, 9]):
        with pytest.raises(ValueError):
            lights.highlight("Rack1", units)
    assert lights.clients["10.0.0.1"].states == []
    assert lights.showing["Rack1"] == ()


def test_failed_write_does_not_change_what_we_think_is_shown(lights):
    lights.highlight("Rack1", [1])

    def unreachable(state):
        raise OSError("timed out")
    lights.clients["10.0.0.1"].set_state = unreachable

    with pytest.raises(OSError):
        lights.highlight("Rack2", [5])
    assert lights.showing["Rack2"] == ()
    assert lights.showing["Rack1"] == (1,)
