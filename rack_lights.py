"""What the front-end API will call: idle() or highlight([1, 2]) per rack.

Racks can share a controller, and WLED renumbers segments when one is
deleted (they are a packed list, not fixed slots). So a rack can't own
"segments 8-15" and update them alone: deleting one of Rack1's segments
would shift Rack2's IDs down under it. Instead every update rebuilds the
whole controller from what each of its racks should be showing, numbering
segments from 0 with no gaps, and deletes whatever is left above that.
"""

import threading

from modes.animate import default_animation
from modes.highlight import highlight_node, unit_groups
from wled_client import WLEDClient

IDLE = ()


def controller_state(segment_lists, max_segments):
    """Number the segments 0..n-1 and delete slots n..max-1."""
    segments = [seg for segs in segment_lists for seg in segs]
    if len(segments) > max_segments:
        raise ValueError(f"{len(segments)} segments, controller has {max_segments}")
    numbered = [{"id": i, **seg} for i, seg in enumerate(segments)]
    numbered += [{"id": i, "stop": 0} for i in range(len(segments), max_segments)]
    return {"on": True, "bri": 255, "seg": numbered}


class RackLights:
    def __init__(self, cfg, client_factory=WLEDClient):
        self.cfg = cfg
        self.clients = {ip: client_factory(ip) for ip in cfg.controllers}
        self.locks = {ip: threading.Lock() for ip in cfg.controllers}
        # What each rack should show: IDLE or a tuple of U numbers.
        self.showing = {name: IDLE for name in cfg.racks}

    def _rack(self, name):
        if name not in self.cfg.racks:
            raise KeyError(f"unknown rack {name!r}; known: {', '.join(self.cfg.racks)}")
        return self.cfg.racks[name]

    def _push(self, ip, changes):
        """Apply `changes` ({rack: IDLE|units}) and rewrite the controller.

        The new state is only kept if the controller accepted it, so a failed
        write doesn't leave this process believing something the LEDs don't
        show.
        """
        with self.locks[ip]:
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

    def idle(self, name):
        rack = self._rack(name)
        self._push(rack.led_ip, {name: IDLE})

    def idle_all(self):
        for ip, names in self.cfg.controllers.items():
            self._push(ip, {name: IDLE for name in names})

    def highlight(self, name, units):
        """Highlight `units` on rack `name`. An empty selection goes back to idle."""
        rack = self._rack(name)
        if not units:
            self.idle(name)
            return
        units = tuple(sorted(set(units)))
        unit_groups(self.cfg, rack, units)   # reject bad requests before touching the network
        self._push(rack.led_ip, {name: units})
