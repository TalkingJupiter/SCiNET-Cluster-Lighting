"""What `GET /status` reports: can each controller be reached, and does it
look the way the config says it should.

`GET /racks` only says what the server last sent. To know whether a
controller is actually there, it has to be asked: `GET /json/info` returns
its WLED version, LED count and uptime.

Probing is on demand and cached. The first `/status` call probes every
controller at once (one thread each, short timeout), and calls within the
next CACHE_S seconds reuse that answer, so a dashboard polling every second
costs each controller one small GET every few seconds. A call that arrives
while a probe is running waits for it instead of starting another.

A probe takes the controller's lock, like every write does. The ESP8266
handles only a few connections, and WLED builds every JSON reply in one
shared buffer, answering "busy" to a request that arrives while it's in
use. A probe landing in the middle of a highlight could make the highlight
fail, so they take turns. If the lock is held for longer than the probe
timeout, the write is hanging on a controller that isn't answering, and
the probe reports it unreachable rather than queueing behind it.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

PROBE_TIMEOUT_S = 1.5
CACHE_S = 5.0


def expected_led_count(cfg, ip):
    """LEDs the config uses on controller `ip`: the end of its last side."""
    return max(side.stop for name in cfg.controllers[ip] for side in cfg.racks[name].sides)


def parse_info(info):
    """(version, LED count, uptime in s) from a /json/info reply."""
    if not isinstance(info, dict):
        raise ValueError(f"unexpected /json/info reply: {info!r}")
    leds = info.get("leds") or {}
    if not isinstance(leds, dict):
        raise ValueError(f"unexpected /json/info leds: {leds!r}")
    return info.get("ver"), leds.get("count"), info.get("uptime")


def overall(controllers):
    """`ok` if every controller is reachable with the LED count the config
    expects, `down` if none is reachable, `degraded` in between."""
    reachable = [c["reachable"] for c in controllers.values()]
    if not any(reachable):
        return "down"
    if all(reachable) and not any(c["led_count_mismatch"] for c in controllers.values()):
        return "ok"
    return "degraded"


def _utcnow():
    return datetime.now(timezone.utc)


class ControllerChecker:
    def __init__(self, cfg, lights, timeout_s=PROBE_TIMEOUT_S, max_age_s=CACHE_S,
                 clock=time.monotonic, wall_clock=_utcnow):
        self.cfg = cfg
        self.lights = lights
        self.timeout_s = timeout_s
        self.max_age_s = max_age_s
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()      # one probe round at a time
        self._checked = None               # self._clock() of the last round
        self._results = {}
        self._uptime = {}                  # last uptime seen, kept across failures
        self._reboots = {ip: 0 for ip in cfg.controllers}

    def controllers(self):
        """Every controller's status, probing them if the cache is stale."""
        with self._lock:
            if self._checked is None or self._clock() - self._checked >= self.max_age_s:
                with ThreadPoolExecutor(max_workers=max(1, len(self.cfg.controllers))) as pool:
                    results = pool.map(self._check, self.cfg.controllers)
                    self._results = dict(zip(self.cfg.controllers, results))
                self._checked = self._clock()
            return dict(self._results)

    def _probe(self, ip):
        lock = self.lights.locks[ip]
        if not lock.acquire(timeout=self.timeout_s):
            raise TimeoutError(f"a write has held the controller for over {self.timeout_s:g} s")
        try:
            return parse_info(self.lights.clients[ip].info(timeout=self.timeout_s))
        finally:
            lock.release()

    def _check(self, ip):
        expected = expected_led_count(self.cfg, ip)
        result = {
            "reachable": False,
            "racks": list(self.cfg.controllers[ip]),
            "wled_version": None,
            "led_count": None,
            "expected_led_count": expected,
            "led_count_mismatch": None,
            "uptime_s": None,
            "reboots": self._reboots[ip],
            "last_error": None,
            "checked_at": self._wall_clock(),
        }
        try:
            version, count, uptime = self._probe(ip)
        except (OSError, ValueError) as exc:
            result["last_error"] = str(exc) or type(exc).__name__
            return result
        # Uptime going backwards means it rebooted. The meter refresh
        # resends its state within RESEND_S; this only makes it visible.
        if uptime is not None:
            if ip in self._uptime and uptime < self._uptime[ip]:
                self._reboots[ip] += 1
            self._uptime[ip] = uptime
        result.update(
            reachable=True,
            wled_version=version,
            led_count=count,
            led_count_mismatch=count != expected,
            uptime_s=uptime,
            reboots=self._reboots[ip],
        )
        return result
