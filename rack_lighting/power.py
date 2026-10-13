"""Latest power reading per rack, pushed by DevOps through PUT /racks/{rack}/power."""

import threading
import time
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Reading:
    kw: float | None          # None = DevOps has no data for this rack
    measured_at: datetime     # when DevOps measured it (their clock)
    received_at: float        # when we received it (our clock)


class PowerStore:
    def __init__(self, racks, stale_after_s, clock=time.monotonic):
        self.stale_after_s = stale_after_s
        self._clock = clock
        self._lock = threading.Lock()
        self._readings = {}               # rack name -> Reading

    def update(self, rack, kw, measured_at):
        """Store a reading. Return False if it was ignored as old."""
        with self._lock:
            old = self._readings.get(rack)
            if old is not None and old.measured_at >= measured_at:
                return False
            self._readings[rack] = Reading(kw, measured_at, self._clock())
            return True

    def get(self, rack):
        """The latest reading, or None if there isn't one or it's stale."""
        with self._lock:
            reading = self._readings.get(rack)
            if reading is None:
                return None
            if self._clock() - reading.received_at > self.stale_after_s:
                return None
            return reading
