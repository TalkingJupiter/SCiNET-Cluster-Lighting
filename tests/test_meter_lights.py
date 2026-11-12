"""RackLights in meter mode: idle racks show their kW meter, refreshed from
the power store, and a controller is only written when its state changes.

Test config: Rack1 (sides 0-112 up, 114-226 down) and Rack2 (226-338 up,
340-452 down) share 10.0.0.1; Rack3 is alone on 10.0.0.3. 25 kW lights 56
of 112 pixels.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from rack_lighting.power import PowerStore
from rack_lighting.rack_lights import RESEND_S, RETRY_DOWN_S, RackLights
from tests.conftest import FakeClient, FakeClock, FakeTimers

SOLID, BLINK, BREATHE, CHASE = 0, 1, 2, 28
SHARED, ALONE = "10.0.0.1", "10.0.0.3"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)

NO_DATA_RACK1 = [(0, 112, BLINK), (114, 226, BLINK)]
NO_DATA_RACK2 = [(226, 338, BLINK), (340, 452, BLINK)]
GREEN_25_RACK1 = [(0, 56, SOLID), (170, 226, SOLID)]


@pytest.fixture
def cfg(write_ini):
    return write_ini(mode="meter")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def power(cfg, clock):
    return PowerStore(cfg.racks, cfg.stale_after_seconds, clock=clock)


@pytest.fixture
def timers():
    return FakeTimers()


@pytest.fixture
def lights(cfg, power, timers, clock):
    return RackLights(cfg, client_factory=FakeClient, schedule=timers, power=power, clock=clock)


class Pushes:
    """Push readings like DevOps would, each measured a second later."""

    def __init__(self, power):
        self.power = power
        self.n = 0

    def __call__(self, rack, kw):
        self.n += 1
        self.power.update(rack, kw, T0 + timedelta(seconds=self.n))


@pytest.fixture
def push(power):
    return Pushes(power)


def writes(lights, ip=SHARED):
    return lights.clients[ip].states


def spans(lights, ip=SHARED):
    state = writes(lights, ip)[-1]
    return [(s["start"], s["stop"], s["fx"]) for s in state["seg"] if s.get("stop") != 0]


def unreachable(state):
    raise OSError("timed out")


# ---------------------------------------------------------------- idle is the meter

def test_idle_without_readings_blinks_red(lights):
    lights.idle_all()
    assert spans(lights) == NO_DATA_RACK1 + NO_DATA_RACK2


def test_idle_shows_the_current_reading(lights, push):
    push("Rack1", 25)
    lights.idle_all()
    assert spans(lights) == GREEN_25_RACK1 + NO_DATA_RACK2


def test_zero_kw_rack_is_dark_next_to_a_no_data_rack(lights, push):
    push("Rack1", 0)
    lights.idle_all()
    assert spans(lights) == NO_DATA_RACK2


def test_chase_mode_is_unchanged(write_ini, power, push):
    """A reading in the store doesn't matter when the mode is chase."""
    lights = RackLights(write_ini(), client_factory=FakeClient, power=power)
    push("Rack1", 25)
    lights.idle_all()
    assert {fx for _, _, fx in spans(lights)} == {CHASE}


def test_without_a_store_every_rack_has_no_data(cfg):
    """The CLI has no readings; it must not crash, just show no data."""
    lights = RackLights(cfg, client_factory=FakeClient)
    lights.idle_all()
    assert spans(lights) == NO_DATA_RACK1 + NO_DATA_RACK2


# ---------------------------------------------------------------- refresh

def test_refresh_draws_a_new_reading(lights, push):
    lights.idle_all()
    push("Rack1", 25)
    assert lights.refresh() == []
    assert spans(lights) == GREEN_25_RACK1 + NO_DATA_RACK2


def test_refresh_writes_nothing_when_nothing_changed(lights, push):
    push("Rack1", 25)
    lights.idle_all()
    before = {ip: len(writes(lights, ip)) for ip in lights.clients}
    lights.refresh()
    lights.refresh()
    assert {ip: len(writes(lights, ip)) for ip in lights.clients} == before


def test_refresh_only_writes_the_controller_that_changed(lights, push):
    lights.idle_all()
    push("Rack3", 25)
    lights.refresh()
    assert len(writes(lights, SHARED)) == 1, "Rack1/Rack2 unchanged"
    assert len(writes(lights, ALONE)) == 2


def test_same_bar_height_is_not_a_change(lights, push):
    """25.0 and 25.1 kW both light 56 pixels; the LEDs would look identical."""
    push("Rack1", 25.0)
    lights.idle_all()
    push("Rack1", 25.1)
    lights.refresh()
    assert len(writes(lights)) == 1


def test_refresh_shows_no_data_once_a_reading_goes_stale(lights, push, clock):
    push("Rack1", 25)
    lights.idle_all()
    clock.now = 30
    lights.refresh()
    assert spans(lights)[:2] == GREEN_25_RACK1, "30 s: still fresh"
    clock.now = 31
    lights.refresh()
    assert spans(lights)[:2] == NO_DATA_RACK1


def test_refresh_before_anything_was_written_writes(lights):
    """The first refresh has nothing to compare against, so it writes."""
    lights.refresh()
    assert len(writes(lights, SHARED)) == 1
    assert len(writes(lights, ALONE)) == 1


# ---------------------------------------------------------------- resend

def test_unchanged_state_is_resent_after_resend_s(lights, push, clock):
    """A controller that rebooted has forgotten its segments; we can't tell,
    so send the same state again now and then."""
    push("Rack1", 25)
    clock.now = 100
    lights.idle_all()
    clock.now = 100 + RESEND_S - 1
    lights.refresh()
    assert len(writes(lights)) == 1, "not yet"
    clock.now = 100 + RESEND_S
    lights.refresh()
    assert len(writes(lights)) == 2
    assert writes(lights)[-1] == writes(lights)[0], "the same state again"


def test_resend_timer_restarts_after_every_write(lights, push, clock):
    lights.idle_all()
    clock.now = RESEND_S - 10
    push("Rack1", 25)
    lights.refresh()                                # a change: written
    clock.now = RESEND_S
    lights.refresh()
    assert len(writes(lights)) == 2, "only 10 s since the last write"


def test_highlight_counts_as_a_write_for_resend(lights, clock):
    lights.idle_all()
    clock.now = RESEND_S - 1
    lights.highlight("Rack1", [1])
    clock.now = RESEND_S
    lights.refresh()
    assert len(writes(lights)) == 2


def test_failed_resend_is_tried_again_after_the_backoff(lights, clock):
    lights.idle_all()
    real = lights.clients[SHARED].set_state
    lights.clients[SHARED].set_state = unreachable
    clock.now = RESEND_S
    assert lights.refresh() == [SHARED]
    lights.clients[SHARED].set_state = real
    clock.now = RESEND_S + RETRY_DOWN_S
    assert lights.refresh() == []
    assert len(writes(lights)) == 2


def test_chase_mode_only_resends(write_ini, clock):
    """The chase never changes, so refresh() writes nothing until a resend
    is due. This is what brings a rebooted controller back to the chase."""
    lights = RackLights(write_ini(), client_factory=FakeClient, clock=clock)
    lights.idle_all()
    for t in (2, 4, RESEND_S - 1):
        clock.now = t
        lights.refresh()
    assert len(writes(lights)) == 1
    clock.now = RESEND_S
    assert lights.refresh() == []
    assert len(writes(lights)) == 2
    assert {fx for _, _, fx in spans(lights)} == {CHASE}


# ---------------------------------------------------------------- highlights

def test_highlight_keeps_the_neighbours_meter(lights, push):
    push("Rack2", 25)
    lights.highlight("Rack1", [1, 2])
    assert spans(lights) == [
        (0, 6, BREATHE), (220, 226, BREATHE),       # Rack1: U1-U2
        (226, 282, SOLID), (396, 452, SOLID),       # Rack2: 25 kW
    ]


def test_refresh_leaves_a_highlight_alone(lights, push, timers):
    lights.highlight("Rack1", [1, 2])
    push("Rack1", 50)
    lights.refresh()
    assert spans(lights)[:2] == [(0, 6, BREATHE), (220, 226, BREATHE)]
    assert lights.showing["Rack1"] == (1, 2)
    assert len(timers.live()) == 1, "the hold timer is untouched"


def test_refresh_redraws_the_neighbour_of_a_highlighted_rack(lights, push):
    lights.highlight("Rack1", [1, 2])
    push("Rack2", 25)
    lights.refresh()
    assert spans(lights)[2:] == [(226, 282, SOLID), (396, 452, SOLID)]
    assert spans(lights)[:2] == [(0, 6, BREATHE), (220, 226, BREATHE)]


def test_highlight_returns_to_the_meter(lights, push, timers):
    push("Rack3", 25)
    lights.highlight("Rack3", [4])
    timers.fire_all()
    assert spans(lights, ALONE) == GREEN_25_RACK1    # Rack3 has Rack1's layout


def test_full_meters_and_full_highlight_fit_one_controller(lights, push):
    """6 meter segments + 8 highlight segments = 14 of 16."""
    push("Rack2", 50)
    lights.highlight("Rack1", [1, 3, 5, 7])
    assert len(spans(lights)) == 14


# ---------------------------------------------------------------- failures

def test_refresh_skips_a_dead_controller(lights, push):
    lights.clients[SHARED].set_state = unreachable
    push("Rack3", 25)
    assert lights.refresh() == [SHARED]
    assert spans(lights, ALONE) == GREEN_25_RACK1


def test_refresh_retries_a_failed_write(lights, push, clock):
    lights.idle_all()
    real = lights.clients[SHARED].set_state
    lights.clients[SHARED].set_state = unreachable
    push("Rack1", 25)
    lights.refresh()

    lights.clients[SHARED].set_state = real
    clock.now = RETRY_DOWN_S
    push("Rack1", 25)                               # still being pushed
    assert lights.refresh() == []
    assert spans(lights) == GREEN_25_RACK1 + NO_DATA_RACK2


# ---------------------------------------------------------------- dead controllers

class Calls:
    """Counts set_state calls on one controller, failing while `down`."""

    def __init__(self, lights, ip):
        self.n = 0
        self.down = True
        self.real = lights.clients[ip].set_state
        lights.clients[ip].set_state = self

    def __call__(self, state):
        self.n += 1
        if self.down:
            raise OSError("timed out")
        self.real(state)


def test_a_dead_controller_is_left_alone_during_the_backoff(lights, clock):
    """No 3 s timeout on every tick: it's skipped, still reported as down."""
    calls = Calls(lights, SHARED)
    lights.idle_all()
    assert calls.n == 1
    for t in (2, 4, RETRY_DOWN_S - 1):
        clock.now = t
        assert lights.refresh() == [SHARED]
    assert calls.n == 1, "not tried during the backoff"
    clock.now = RETRY_DOWN_S
    lights.refresh()
    assert calls.n == 2, "tried again once it's over"


def test_the_backoff_restarts_after_each_failed_retry(lights, clock):
    calls = Calls(lights, SHARED)
    lights.idle_all()
    clock.now = RETRY_DOWN_S
    lights.refresh()                                # retry fails
    clock.now = RETRY_DOWN_S + 2
    lights.refresh()
    assert calls.n == 2, "waiting again"


def test_other_controllers_keep_refreshing_during_the_backoff(lights, push, clock):
    Calls(lights, SHARED)
    lights.idle_all()
    clock.now = 2
    push("Rack3", 25)
    assert lights.refresh() == [SHARED]
    assert spans(lights, ALONE) == GREEN_25_RACK1


def test_a_controller_that_comes_back_is_rewritten_at_once(lights, push, clock):
    """It probably rebooted and lost its segments, so it gets its state as
    soon as it answers, even when that state is what we last sent it and no
    resend is due yet."""
    calls = Calls(lights, SHARED)
    calls.down = False
    lights.idle_all()                     # t=0: accepted, both racks no data
    calls.down = True
    clock.now = 1
    push("Rack1", 25)
    lights.refresh()                      # the green bar fails: it's down
    push("Rack1", None)                   # DevOps: no data again, so the
                                          # state is back to what it accepted
    calls.down = False
    clock.now = 1 + RETRY_DOWN_S          # well before the 60 s resend
    assert lights.refresh() == []
    assert calls.n == 3, "rewritten although nothing changed"
    assert spans(lights) == NO_DATA_RACK1 + NO_DATA_RACK2


def test_coming_back_is_logged(lights, clock, caplog):
    calls = Calls(lights, SHARED)
    lights.idle_all()
    calls.down = False
    clock.now = RETRY_DOWN_S
    caplog.set_level("INFO")
    lights.refresh()
    assert "controller 10.0.0.1 reachable again" in caplog.text


def test_a_highlight_that_works_ends_the_backoff(lights, clock):
    """The front end found it up again; no need to wait 30 s."""
    calls = Calls(lights, SHARED)
    lights.idle_all()
    calls.down = False
    lights.highlight("Rack1", [1])
    clock.now = 2
    assert lights.refresh() == []


# ---------------------------------------------------------------- in parallel

def blocking(lights, ip):
    """Make controller `ip` hang (like a 3 s timeout) until released."""
    release = threading.Event()
    real = lights.clients[ip].set_state

    def hang(state):
        release.wait(5)
        raise OSError("timed out")
    lights.clients[ip].set_state = hang
    return release, real


def test_a_hanging_controller_does_not_delay_the_others_on_refresh(lights, push):
    lights.idle_all()
    release, _ = blocking(lights, SHARED)
    lights._sent.pop(SHARED)                        # force a write to it
    push("Rack3", 25)
    t = threading.Thread(target=lights.refresh)
    t.start()
    try:
        assert wait_for(lambda: len(writes(lights, ALONE)) == 2), \
            "Rack3 was drawn while 10.0.0.1 still hangs"
    finally:
        release.set()
        t.join()


def test_a_hanging_controller_does_not_delay_startup(lights):
    release, _ = blocking(lights, SHARED)
    t = threading.Thread(target=lights.idle_all)
    t.start()
    try:
        assert wait_for(lambda: len(writes(lights, ALONE)) == 1)
    finally:
        release.set()
        t.join()


def test_startup_failures_are_logged_once_and_backed_off(lights, clock, caplog):
    calls = Calls(lights, SHARED)
    assert lights.idle_all() == [SHARED]
    clock.now = 2
    lights.refresh()
    assert caplog.text.count("unreachable") == 1
    assert calls.n == 1


def test_dead_controller_is_logged_once_not_every_retry(lights, caplog, clock):
    calls = Calls(lights, SHARED)
    for n in range(3):
        clock.now = n * RETRY_DOWN_S              # a real retry each time
        lights.refresh()
    assert calls.n == 3
    assert caplog.text.count("unreachable") == 1


# ---------------------------------------------------------------- background thread

def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_start_meter_refreshes_until_stopped(lights, push):
    lights.idle_all()
    stop = lights.start_meter(interval=0.01)
    try:
        push("Rack1", 25)
        assert wait_for(lambda: spans(lights)[:2] == GREEN_25_RACK1)
    finally:
        stop()
    count = len(writes(lights))
    push("Rack1", 50)
    time.sleep(0.05)
    assert len(writes(lights)) == count, "nothing written after stop()"


def test_meter_thread_survives_a_failing_tick(lights, push, monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
    monkeypatch.setattr(lights, "refresh", flaky)
    stop = lights.start_meter(interval=0.01)
    try:
        assert wait_for(lambda: len(calls) >= 3)
    finally:
        stop()
