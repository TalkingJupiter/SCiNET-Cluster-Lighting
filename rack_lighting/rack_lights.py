"""Rack LED state: idle (chase or kW meter), or a highlight that expires on its own.

The front end only ever asks for highlights. It does not decide when a rack
goes back to idle: every highlight holds for `[Highlight] hold-seconds` and
then this module returns the rack to the chase itself. A new highlight on the
same rack replaces the old one and restarts the timer.

Racks can share a controller, and WLED renumbers segments when one is
deleted (they are a packed list, not fixed slots). So a rack can't own
"segments 8-15" and update them alone: deleting one of Rack1's segments
would shift Rack2's IDs down under it. Instead every update rebuilds the
whole controller from what each of its racks should be showing, numbering
segments from 0 with no gaps, and deletes whatever is left above that.

In `meter` mode "idle" means the kW meter. Readings change without anyone
calling us, so `refresh()` redraws every controller from the latest readings
and only writes the ones whose state actually changed; `start_meter()` calls
it every couple of seconds on a background thread.

A controller that loses power forgets its segments, and we'd never notice:
nothing changed on our side. So `refresh()` also resends each controller's
state at least every RESEND_S seconds, in either mode.
"""

import logging
import threading
import time

from .clients.wled_client import WLEDClient
from .modes.animate import default_animation
from .modes.highlight import highlight_node, unit_groups
from .modes.kw_meter import kw_meter
from .power import PowerStore

log = logging.getLogger(__name__)

IDLE = ()
METER_REFRESH_S = 2.0
RESEND_S = 60.0


def controller_state(segment_lists, max_segments):
    """Number the segments 0..n-1 and delete slots n..max-1."""
    segments = [seg for segs in segment_lists for seg in segs]
    if len(segments) > max_segments:
        raise ValueError(f"{len(segments)} segments, controller has {max_segments}")
    numbered = [{"id": i, **seg} for i, seg in enumerate(segments)]
    numbered += [{"id": i, "stop": 0} for i in range(len(segments), max_segments)]
    return {"on": True, "bri": 255, "seg": numbered}


def thread_timer(delay, fn):
    """Run fn after delay seconds. Returns something with .cancel().

    Not a daemon thread: if the process is asked to exit while a rack is
    highlighted, it waits for the timer and leaves the rack chasing, not lit
    white forever.
    """
    timer = threading.Timer(delay, fn)
    timer.start()
    return timer


class RackLights:
    def __init__(self, cfg, client_factory=WLEDClient, schedule=thread_timer,
                 power=None, clock=time.monotonic):
        self.cfg = cfg
        self._clock = clock
        # Readings for the meter. Without one (e.g. the CLI) every rack has
        # no data, which the meter shows honestly as blinking red.
        self.power = power or PowerStore(cfg.racks, cfg.stale_after_seconds)
        self.clients = {ip: client_factory(ip) for ip in cfg.controllers}
        self.locks = {ip: threading.Lock() for ip in cfg.controllers}
        # What each rack should show: IDLE or a tuple of U numbers.
        self.showing = {name: IDLE for name in cfg.racks}
        self._schedule = schedule
        self._timers = {}
        # Bumped on every highlight. An expiry only fires if nothing newer
        # has happened on that rack since it was scheduled.
        self._generation = {name: 0 for name in cfg.racks}
        # When each armed hold timer is due, on self._clock, for GET /status.
        self._hold_until = {}
        # Last state each controller accepted, and when, so refresh() can
        # skip writes that would change nothing (until a resend is due).
        self._sent = {}
        self._sent_at = {}
        self._unreachable = set()

    def _rack(self, name):
        if name not in self.cfg.racks:
            raise KeyError(f"unknown rack {name!r}; known: {', '.join(self.cfg.racks)}")
        return self.cfg.racks[name]

    def _idle_segments(self, rack, effects):
        if self.cfg.mode == "meter":
            return kw_meter(self.cfg, rack, effects, self.power.get(rack.name))
        return default_animation(self.cfg, rack, effects)

    def _write(self, ip, changes, only_if_changed=False):
        """Rewrite controller `ip` with `changes` applied. Caller holds the lock.

        The new state is only kept if the controller accepted it, so a failed
        write doesn't leave this process believing something the LEDs don't
        show (and the next refresh tries again).
        """
        client = self.clients[ip]
        effects = client.effects()
        wanted = {**self.showing, **changes}
        lists = []
        for name in self.cfg.controllers[ip]:
            rack = self.cfg.racks[name]
            units = wanted[name]
            if units:
                lists.append(highlight_node(self.cfg, rack, effects, units))
            else:
                lists.append(self._idle_segments(rack, effects))
        state = controller_state(lists, self.cfg.max_segments)
        if only_if_changed and state == self._sent.get(ip) and not self._resend_due(ip):
            return
        client.set_state(state)
        self._sent[ip] = state
        self._sent_at[ip] = self._clock()
        self.showing.update(changes)

    def _resend_due(self, ip):
        return self._clock() - self._sent_at[ip] >= RESEND_S

    # ------------------------------------------------------------ idle

    def idle(self, name):
        rack = self._rack(name)
        with self.locks[rack.led_ip]:
            self._generation[name] += 1       # cancels any pending expiry
            self._write(rack.led_ip, {name: IDLE})

    def idle_all(self):
        """Every rack to idle. A controller that is down is logged and
        skipped, so one dead controller doesn't keep the rest dark.
        Returns the controller IPs that failed."""
        failed = []
        for ip, names in self.cfg.controllers.items():
            try:
                with self.locks[ip]:
                    for name in names:
                        self._generation[name] += 1
                    self._write(ip, {name: IDLE for name in names})
            except OSError as exc:
                log.warning("controller %s unreachable: %s", ip, exc)
                failed.append(ip)
        return failed

    # ------------------------------------------------------------ highlight

    def highlight(self, name, units):
        """Highlight `units` on rack `name` for hold-seconds, then idle."""
        rack = self._rack(name)
        units = tuple(sorted(set(units)))
        unit_groups(self.cfg, rack, units)   # reject bad requests before touching the network

        with self.locks[rack.led_ip]:
            self._write(rack.led_ip, {name: units})
            self._generation[name] += 1
            generation = self._generation[name]

        self._arm(name, generation, self.cfg.highlight_hold_s)
        return units

    def _arm(self, name, generation, delay):
        old = self._timers.pop(name, None)
        if old is not None:
            old.cancel()
        self._timers[name] = self._schedule(delay, lambda: self._expire(name, generation))
        self._hold_until[name] = self._clock() + delay

    def hold_remaining(self, name):
        """Seconds until highlighted rack `name` goes back to idle, or None if
        it is idle. After a failed return to idle, the time until the retry."""
        until = self._hold_until.get(name)
        if until is None or not self.showing[name]:
            return None
        return max(0.0, until - self._clock())

    def _expire(self, name, generation):
        """Timer callback: back to idle, unless something newer happened.

        The generation check and the write happen under the controller lock,
        so a highlight that arrives at the same moment can't be overwritten
        by the expiry of the one it replaced.
        """
        rack = self.cfg.racks[name]
        try:
            with self.locks[rack.led_ip]:
                if self._generation[name] != generation:
                    return
                self._write(rack.led_ip, {name: IDLE})
        except OSError as exc:
            # Leaving a rack highlighted forever is the one outcome we must
            # not allow, so keep trying until it works or is superseded.
            log.warning("%s: could not return to idle (%s); retrying", name, exc)
            self._arm(name, generation, self.cfg.highlight_hold_s)
            return
        self._timers.pop(name, None)

    # ------------------------------------------------------------ meter

    def refresh(self):
        """Redraw idle racks' meters from the latest readings.

        A controller is written only if its state changed, or if RESEND_S
        has passed since its last write (in case it rebooted). Highlighted
        racks keep their highlight. In chase mode nothing ever changes, so
        this only resends. A controller that is down is skipped and retried
        next time. Returns the controller IPs that failed.
        """
        failed = []
        for ip in self.cfg.controllers:
            try:
                with self.locks[ip]:
                    self._write(ip, {}, only_if_changed=True)
            except OSError as exc:
                failed.append(ip)
                if ip not in self._unreachable:     # log once, not every tick
                    log.warning("controller %s unreachable: %s", ip, exc)
                continue
            if ip in self._unreachable:
                log.info("controller %s reachable again", ip)
        self._unreachable = set(failed)
        return failed

    def run_meter(self, stop, interval=METER_REFRESH_S):
        """Call refresh() every `interval` seconds until `stop` (an Event) is set."""
        while not stop.wait(interval):
            try:
                self.refresh()
            except Exception:
                # A bug in one tick must not stop the meter for good.
                log.exception("meter refresh failed")

    def start_meter(self, interval=METER_REFRESH_S):
        """Run refresh() on a background thread. Returns a function that stops it."""
        stop = threading.Event()
        thread = threading.Thread(
            target=self.run_meter, args=(stop, interval), name="kw-meter", daemon=True
        )
        thread.start()

        def stop_meter():
            stop.set()
            thread.join()
        return stop_meter
