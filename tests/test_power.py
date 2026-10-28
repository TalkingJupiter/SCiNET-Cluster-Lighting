from datetime import datetime, timezone

from rack_lighting.power import PowerStore
from tests.conftest import FakeClock


def at(second):
    """A DevOps measured_at timestamp, `second` seconds into the minute."""
    return datetime(2026, 10, 12, 14, 3, second, tzinfo=timezone.utc)


def make_store(clock=None):
    return PowerStore(["Rack1"], 30, clock=clock or FakeClock())


def test_nothing_before_the_first_reading():
    assert make_store().get("Rack1") is None


def test_stores_and_returns_a_reading():
    store = make_store()
    assert store.update("Rack1", 12.4, at(2)) is True
    reading = store.get("Rack1")
    assert reading.kw == 12.4
    assert reading.measured_at == at(2)


def test_newer_reading_replaces_the_old_one():
    store = make_store()
    store.update("Rack1", 12.4, at(2))
    assert store.update("Rack1", 13.0, at(7)) is True
    assert store.get("Rack1").kw == 13.0


def test_older_reading_is_ignored():
    """Requests can arrive out of order; an older measurement must not
    overwrite a newer one."""
    store = make_store()
    store.update("Rack1", 12.4, at(5))
    assert store.update("Rack1", 11.0, at(3)) is False
    assert store.get("Rack1").kw == 12.4


def test_same_reading_twice_is_ignored():
    """A resent reading isn't new, so it must not keep the rack fresh."""
    clock = FakeClock()
    store = make_store(clock)
    store.update("Rack1", 12.4, at(5))
    clock.now = 25
    assert store.update("Rack1", 12.4, at(5)) is False
    clock.now = 31
    assert store.get("Rack1") is None, "staleness counts from the first receipt"


def test_no_data_is_stored():
    """DevOps saying 'no data' (kw=None) is different from hearing nothing."""
    store = make_store()
    store.update("Rack1", None, at(2))
    reading = store.get("Rack1")
    assert reading is not None
    assert reading.kw is None


def test_goes_stale_after_stale_after_seconds():
    clock = FakeClock()
    store = make_store(clock)
    store.update("Rack1", 12.4, at(2))
    clock.now = 30
    assert store.get("Rack1").kw == 12.4      # exactly 30 s: still fresh
    clock.now = 31
    assert store.get("Rack1") is None         # 31 s: stale


def test_a_new_reading_makes_a_stale_rack_fresh_again():
    clock = FakeClock()
    store = make_store(clock)
    store.update("Rack1", 12.4, at(2))
    clock.now = 40
    assert store.get("Rack1") is None
    store.update("Rack1", 9.8, at(42))
    assert store.get("Rack1").kw == 9.8


def test_racks_are_independent():
    store = PowerStore(["Rack1", "Rack2"], 30, clock=FakeClock())
    store.update("Rack1", 12.4, at(5))
    assert store.update("Rack2", 3.1, at(1)) is True, "Rack1's time doesn't apply"
    assert store.get("Rack1").kw == 12.4
    assert store.get("Rack2").kw == 3.1
