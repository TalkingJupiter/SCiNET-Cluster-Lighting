"""GET /health and GET /status, and the controller probes behind /status.

Test config: Rack1 and Rack2 share 10.0.0.1 (sides end at pixel 452);
Rack3 is alone on 10.0.0.3 (226). FakeClient.info() answers like a healthy
WLED with those LED counts.
"""

import threading
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from rack_lighting import config_loader
from rack_lighting.api import create_app
from rack_lighting.power import PowerStore
from rack_lighting.rack_lights import RackLights
from rack_lighting.status import (
    CACHE_S, PROBE_TIMEOUT_S, ControllerChecker, expected_led_count, overall, parse_info,
)
from tests.conftest import FakeClient, FakeClock, FakeTimers

SHARED, ALONE = "10.0.0.1", "10.0.0.3"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def timers():
    return FakeTimers()


@pytest.fixture
def power(cfg, clock):
    return PowerStore(cfg.racks, cfg.stale_after_seconds, clock=clock)


@pytest.fixture
def lights(cfg, timers, power, clock):
    return RackLights(cfg, client_factory=FakeClient, schedule=timers, power=power, clock=clock)


@pytest.fixture
def checker(cfg, lights, clock):
    return ControllerChecker(cfg, lights, clock=clock, wall_clock=lambda: T0)


@pytest.fixture
def api(cfg, lights, power, checker):
    with TestClient(create_app(cfg, lights, power, checker)) as client:
        yield client


def unreachable(*args, **kwargs):
    raise OSError("timed out")


def all_down(lights):
    for client in lights.clients.values():
        client.info = unreachable
        client.set_state = unreachable


def info_calls(lights, ip):
    return len(lights.clients[ip].info_timeouts)


# ---------------------------------------------------------------- pure parts

def test_expected_led_count_is_the_end_of_the_last_side(cfg):
    assert expected_led_count(cfg, SHARED) == 452
    assert expected_led_count(cfg, ALONE) == 226


def test_expected_led_count_in_the_real_config(monkeypatch):
    """Paired racks end at pixel 602, a DNOC rack alone at 301."""
    monkeypatch.setattr(config_loader, "load_dotenv", lambda: None)
    cfg = config_loader.load()
    counts = {ip: expected_led_count(cfg, ip) for ip in cfg.controllers}
    assert counts["140.221.240.5"] == 602
    assert counts["140.221.240.9"] == 301
    assert set(counts.values()) == {602, 301}


def c(reachable, mismatch=False):
    return {"reachable": reachable, "led_count_mismatch": mismatch if reachable else None}


@pytest.mark.parametrize("controllers, expected", [
    ({"a": c(True), "b": c(True)}, "ok"),
    ({"a": c(True), "b": c(False)}, "degraded"),
    ({"a": c(True), "b": c(True, mismatch=True)}, "degraded"),
    ({"a": c(False), "b": c(False)}, "down"),
])
def test_overall(controllers, expected):
    assert overall(controllers) == expected


def test_parse_info():
    info = {"ver": "0.15.0", "leds": {"count": 602, "fps": 42}, "uptime": 84211, "name": "WLED"}
    assert parse_info(info) == ("0.15.0", 602, 84211)


def test_parse_info_rejects_a_reply_that_is_not_info():
    with pytest.raises(ValueError):
        parse_info(None)


# ---------------------------------------------------------------- probes

def test_healthy_controller(checker):
    assert checker.controllers()[SHARED] == {
        "reachable": True,
        "racks": ["Rack1", "Rack2"],
        "wled_version": "0.15.0",
        "led_count": 452,
        "expected_led_count": 452,
        "led_count_mismatch": False,
        "uptime_s": 1000,
        "reboots": 0,
        "last_error": None,
        "checked_at": T0,
    }


def test_led_count_mismatch_is_flagged(checker, lights):
    """The likeliest bring-up mistake: config and hardware disagree."""
    lights.clients[ALONE].led_count = 300
    result = checker.controllers()[ALONE]
    assert (result["led_count"], result["expected_led_count"]) == (300, 226)
    assert result["led_count_mismatch"] is True
    assert checker.controllers()[SHARED]["led_count_mismatch"] is False


def test_unreachable_controller(checker, lights):
    lights.clients[ALONE].info = unreachable
    result = checker.controllers()[ALONE]
    assert result["reachable"] is False
    assert result["last_error"] == "timed out"
    assert (result["wled_version"], result["led_count"], result["uptime_s"]) == (None, None, None)
    assert result["led_count_mismatch"] is None
    assert result["expected_led_count"] == 226, "still known from the config"
    assert checker.controllers()[SHARED]["reachable"] is True


def test_garbage_reply_counts_as_unreachable(checker, lights):
    lights.clients[ALONE].info = lambda timeout=None: None
    result = checker.controllers()[ALONE]
    assert result["reachable"] is False
    assert "unexpected /json/info reply" in result["last_error"]


def test_error_clears_once_the_controller_answers(checker, lights, clock):
    real = lights.clients[ALONE].info
    lights.clients[ALONE].info = unreachable
    checker.controllers()
    lights.clients[ALONE].info = real
    clock.now = CACHE_S
    result = checker.controllers()[ALONE]
    assert (result["reachable"], result["last_error"]) == (True, None)


def test_probes_use_the_short_timeout(checker, lights):
    checker.controllers()
    assert lights.clients[SHARED].info_timeouts == [PROBE_TIMEOUT_S]


def test_results_are_cached(checker, lights, clock):
    """A dashboard polling /status must not flood the controllers."""
    checker.controllers()
    clock.now = CACHE_S - 0.1
    checker.controllers()
    assert info_calls(lights, SHARED) == info_calls(lights, ALONE) == 1
    clock.now = CACHE_S
    checker.controllers()
    assert info_calls(lights, SHARED) == info_calls(lights, ALONE) == 2


def test_probes_run_in_parallel(checker, lights):
    """Both probes must be in flight at once to get past the barrier; one
    after the other, the first would time out waiting for the second."""
    barrier = threading.Barrier(len(lights.clients), timeout=2)

    def meet(timeout=None):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            raise OSError("probes ran one at a time")
        return {"ver": "0.15.0", "leds": {"count": 0}, "uptime": 1}
    for client in lights.clients.values():
        client.info = meet
    assert all(r["reachable"] for r in checker.controllers().values())


def test_concurrent_calls_share_one_probe(checker, lights):
    """A /status that arrives during a probe waits for it instead of
    probing again."""
    release = threading.Event()
    real = lights.clients[SHARED].info

    def slow(timeout=None):
        release.wait(2)
        return real(timeout)
    lights.clients[SHARED].info = slow

    threads = [threading.Thread(target=checker.controllers) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join()
    assert len(lights.clients[SHARED].info_timeouts) == 1


def test_probe_holds_the_controller_lock(checker, lights):
    """So a probe never lands in the middle of a write."""
    held = []
    real = lights.clients[SHARED].info

    def check(timeout=None):
        held.append(lights.locks[SHARED].locked())
        return real(timeout)
    lights.clients[SHARED].info = check
    checker.controllers()
    assert held == [True]


def test_probe_gives_up_on_a_write_that_hangs(cfg, lights, clock):
    """A write holding the lock past the probe timeout means the controller
    isn't answering; don't queue behind it."""
    checker = ControllerChecker(cfg, lights, timeout_s=0.05, clock=clock)
    with lights.locks[ALONE]:
        result = checker.controllers()[ALONE]
    assert result["reachable"] is False
    assert "write" in result["last_error"]
    assert info_calls(lights, ALONE) == 0
    assert checker.controllers()[SHARED]["reachable"] is True


def test_reboot_is_counted_when_uptime_goes_down(checker, lights, clock):
    client = lights.clients[ALONE]
    client.uptime = 1000
    checker.controllers()
    clock.now += CACHE_S
    client.uptime = 1005
    assert checker.controllers()[ALONE]["reboots"] == 0
    clock.now += CACHE_S
    client.uptime = 3
    result = checker.controllers()[ALONE]
    assert (result["uptime_s"], result["reboots"]) == (3, 1)
    clock.now += CACHE_S
    client.uptime = 8
    assert checker.controllers()[ALONE]["reboots"] == 1


def test_reboot_is_counted_across_an_outage(checker, lights, clock):
    """A reboot usually looks like: gone for a while, back with low uptime."""
    client = lights.clients[ALONE]
    real = client.info
    checker.controllers()
    client.info = unreachable
    clock.now += CACHE_S
    assert checker.controllers()[ALONE]["reboots"] == 0
    client.info = real
    client.uptime = 4
    clock.now += CACHE_S
    assert checker.controllers()[ALONE]["reboots"] == 1


# ---------------------------------------------------------------- GET /health

def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


def test_health_answers_with_every_controller_down(cfg, lights, power, checker):
    all_down(lights)
    with TestClient(create_app(cfg, lights, power, checker)) as api:
        r = api.get("/health")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})


def test_health_makes_no_controller_calls(api, lights):
    before = {ip: (len(c.states), len(c.info_timeouts)) for ip, c in lights.clients.items()}
    api.get("/health")
    assert {ip: (len(c.states), len(c.info_timeouts)) for ip, c in lights.clients.items()} == before


# ---------------------------------------------------------------- GET /status

def test_status_ok(api):
    r = api.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["mode"]) == ("ok", "chase")
    assert body["controllers"][ALONE] == {
        "reachable": True,
        "racks": ["Rack3"],
        "wled_version": "0.15.0",
        "led_count": 226,
        "expected_led_count": 226,
        "led_count_mismatch": False,
        "uptime_s": 1000,
        "reboots": 0,
        "last_error": None,
        "checked_at": "2026-11-05T12:00:00Z",
    }
    assert body["racks"]["Rack1"] == {
        "showing": "idle", "hold_remaining_s": None, "kw": None, "kw_age_s": None,
    }


def test_status_degraded_when_one_controller_is_down(api, lights):
    lights.clients[ALONE].info = unreachable
    r = api.get("/status")
    assert (r.status_code, r.json()["status"]) == (200, "degraded")
    assert r.json()["controllers"][ALONE]["last_error"] == "timed out"


def test_status_degraded_on_led_count_mismatch(api, lights):
    lights.clients[SHARED].led_count = 450
    r = api.get("/status")
    assert (r.status_code, r.json()["status"]) == (200, "degraded")


def test_status_down_is_503_with_the_full_report(cfg, lights, power, checker):
    all_down(lights)
    with TestClient(create_app(cfg, lights, power, checker)) as api:
        r = api.get("/status")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "down"
    assert {ip: c["reachable"] for ip, c in body["controllers"].items()} == {
        SHARED: False, ALONE: False,
    }
    assert set(body["racks"]) == {"Rack1", "Rack2", "Rack3"}


def test_status_shows_the_hold_counting_down(api, clock, timers):
    clock.now = 100
    api.post("/racks/Rack1/highlight", json={"units": [2, 1]})
    clock.now = 102
    racks = api.get("/status").json()["racks"]
    assert racks["Rack1"]["showing"] == [1, 2]
    assert racks["Rack1"]["hold_remaining_s"] == 3.0
    assert racks["Rack2"]["hold_remaining_s"] is None

    timers.fire_all()
    rack1 = api.get("/status").json()["racks"]["Rack1"]
    assert (rack1["showing"], rack1["hold_remaining_s"]) == ("idle", None)


def test_new_highlight_restarts_the_hold(api, clock):
    api.post("/racks/Rack1/highlight", json={"units": [1]})
    clock.now = 4
    api.post("/racks/Rack1/highlight", json={"units": [3]})
    assert api.get("/status").json()["racks"]["Rack1"]["hold_remaining_s"] == 5.0


def test_status_shows_the_power_reading(api, power, clock):
    power.update("Rack1", 12.4, T0)
    clock.now = 3
    racks = api.get("/status").json()["racks"]
    assert (racks["Rack1"]["kw"], racks["Rack1"]["kw_age_s"]) == (12.4, 3.0)
    assert (racks["Rack2"]["kw"], racks["Rack2"]["kw_age_s"]) == (None, None)


def test_repeated_status_calls_probe_once(api, lights):
    for _ in range(5):
        api.get("/status")
    assert info_calls(lights, SHARED) == 1
