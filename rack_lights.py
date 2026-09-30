"""Rack LED state: idle chase, or a highlight that expires on its own.

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
"""

import logging
import threading

from modes.animate import default_animation
from modes.highlight import highlight_node, unit_groups
from wled_client import WLEDClient

log = logging.getLogger(__name__)

IDLE = ()


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
    def __init__(self, cfg, client_factory=WLEDClient, schedule=thread_timer):
        self.cfg = cfg
        self.clients = {ip: client_factory(ip) for ip in cfg.controllers}
        self.locks = {ip: threading.Lock() for ip in cfg.controllers}
        # What each rack should show: IDLE or a tuple of U numbers.
        self.showing = {name: IDLE for name in cfg.racks}
        self._schedule = schedule
        self._timers = {}
        # Bumped on every highlight. An expiry only fires if nothing newer
        # has happened on that rack since it was scheduled.
        self._generation = {name: 0 for name in cfg.racks}

    def _rack(self, name):
        if name not in self.cfg.racks:
            raise KeyError(f"unknown rack {name!r}; known: {', '.join(self.cfg.racks)}")
        return self.cfg.racks[name]

    def _write(self, ip, changes):
        """Rewrite controller `ip` with `changes` applied. Caller holds the lock.

        The new state is only kept if the controller accepted it, so a failed
        write doesn't leave this process believing something the LEDs don't
        show.
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
                lists.append(default_animation(self.cfg, rack, effects))
        client.set_state(controller_state(lists, self.cfg.max_segments))
        self.showing.update(changes)

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
