import pytest
from fastapi.testclient import TestClient

from rack_lighting.api import create_app
from rack_lighting.rack_lights import RackLights
from tests.conftest import FakeClient, FakeTimers


@pytest.fixture
def timers():
    return FakeTimers()


@pytest.fixture
def lights(cfg, timers):
    return RackLights(cfg, client_factory=FakeClient, schedule=timers)


@pytest.fixture
def api(cfg, lights):
    with TestClient(create_app(cfg, lights)) as client:   # runs startup
        yield client


def test_startup_puts_every_rack_on_chase(api, lights):
    for client in lights.clients.values():
        assert len(client.states) == 1
    assert api.get("/racks").json() == {
        "Rack1": {"showing": "idle"},
        "Rack2": {"showing": "idle"},
        "Rack3": {"showing": "idle"},
    }


def test_highlight(api, lights):
    r = api.post("/racks/Rack1/highlight", json={"units": [2, 1, 2]})
    assert r.status_code == 200
    assert r.json() == {"rack": "Rack1", "units": [1, 2], "hold_seconds": 5.0}
    assert lights.showing["Rack1"] == (1, 2)
    assert api.get("/racks").json()["Rack1"] == {"showing": [1, 2]}


def test_highlight_expires_back_to_idle(api, lights, timers):
    api.post("/racks/Rack1/highlight", json={"units": [1]})
    timers.fire_all()
    assert api.get("/racks").json()["Rack1"] == {"showing": "idle"}


def test_there_is_no_idle_endpoint(api):
    """The front end cannot decide when a rack goes idle."""
    assert api.post("/racks/Rack1/idle").status_code == 404


def test_unknown_rack_is_404(api):
    r = api.post("/racks/Rack9/highlight", json={"units": [1]})
    assert r.status_code == 404
    assert "unknown rack" in r.json()["detail"]


@pytest.mark.parametrize("body", [
    {"units": []},
    {"units": ["a"]},
    {},
    {"units": [43]},
    {"units": [0]},
    {"units": [1, 3, 5, 7, 9]},          # 5 groups; the limit is 4
])
def test_bad_requests_are_422(api, body, lights):
    before = len(lights.clients["10.0.0.1"].states)
    assert api.post("/racks/Rack1/highlight", json=body).status_code == 422
    assert len(lights.clients["10.0.0.1"].states) == before


def test_too_many_groups_says_why(api):
    r = api.post("/racks/Rack1/highlight", json={"units": [1, 3, 5, 7, 9]})
    assert "At most 4 groups" in r.json()["detail"]


def test_unreachable_controller_is_502(api, lights):
    def unreachable(state):
        raise OSError("timed out")
    lights.clients["10.0.0.3"].set_state = unreachable
    r = api.post("/racks/Rack3/highlight", json={"units": [1]})
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


def test_dead_controller_at_startup_does_not_stop_the_api(cfg, timers):
    lights = RackLights(cfg, client_factory=FakeClient, schedule=timers)

    def unreachable(state):
        raise OSError("timed out")
    lights.clients["10.0.0.1"].set_state = unreachable

    with TestClient(create_app(cfg, lights)) as api:
        assert api.get("/racks").status_code == 200
        assert api.post("/racks/Rack3/highlight", json={"units": [1]}).status_code == 200
