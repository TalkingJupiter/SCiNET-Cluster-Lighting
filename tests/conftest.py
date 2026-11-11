import textwrap

import pytest

from rack_lighting import config_loader

# Same positions as real WLED: Solid = 0, Breathe = 2, Chase = 28.
EFFECTS = ["Solid", "Blink", "Breathe"] + [f"FX{i}" for i in range(3, 28)] + ["Chase"]

# Rack1 and Rack2 share a controller; Rack3 has a controller to itself.
# Sides are 112 pixels, which spreads 42 U's as 3, 3, 2, 3, 3, 2, ... Each
# side B ends where a 113-pixel side would have (226, 452), with one dark
# pixel (112 or 338) between the sides.
BASE_INI = """
[Rack1]
led-ip = 10.0.0.1
side-a = 0, 112, up
side-b = 114, 112, down

[Rack2]
led-ip = 10.0.0.1
side-a = 226, 112, up
side-b = 340, 112, down

[Rack3]
led-ip = 10.0.0.3
side-a = 0, 112, up
side-b = 114, 112, down

[Led-Controller]
mode = chase
max-segments = 16
segments-per-rack = 8

[Units]
u-count = 42

[Idle]
effect = Chase
color = 255, 120, 0
speed = 160
intensity = 128
brightness = 255

[Highlight]
effect = Breathe
color = 255, 255, 255
brightness = 150
speed = 200
hold-seconds = 5

[Energy]
min-kw = 0
max-kw = 50
amber-from-kw = 30
red-from-kw = 40
stale-after-seconds = 30

[Meter]
brightness=200
green = 0, 200, 0
amber = 255, 140, 0
red = 255, 0, 0
no-data-effect = Blink
"""


# What each BASE_INI controller should report: the end of its last side.
LED_COUNTS = {"10.0.0.1": 452, "10.0.0.3": 226}


class FakeClient:
    """Stands in for WLEDClient: records every state written, and answers
    info() like a healthy WLED with the LED count the config expects."""

    def __init__(self, host):
        self.host = host
        self.states = []
        self.led_count = LED_COUNTS.get(host, 0)
        self.uptime = 1000
        self.info_timeouts = []          # the timeout of every info() call

    def effects(self):
        return EFFECTS

    def set_state(self, state):
        self.states.append(state)

    def info(self, timeout=None):
        self.info_timeouts.append(timeout)
        return {"ver": "0.15.0", "leds": {"count": self.led_count}, "uptime": self.uptime}


@pytest.fixture
def write_ini(tmp_path, monkeypatch):
    """Write an ini (BASE_INI with replacements) and load it."""
    monkeypatch.delenv("power_ingest_token", raising=False)
    monkeypatch.setattr(config_loader, "load_dotenv", lambda: None)

    def _write(text=BASE_INI, **replace):
        """Keyword args replace the value of the *first* matching key, e.g.
        side_a="0, 111, up" changes Rack1's side-a only."""
        for old, new in replace.items():
            old = old.replace("_", "-")
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.split("=")[0].strip() == old:
                    lines[i] = f"{old} = {new}"
                    break
            text = "\n".join(lines)
        path = tmp_path / "config.ini"
        path.write_text(textwrap.dedent(text))
        return config_loader.load(str(path))

    return _write


@pytest.fixture
def cfg(write_ini):
    return write_ini()


class FakeTimers:
    """Stands in for thread_timer. Nothing fires until the test says so."""

    def __init__(self):
        self.pending = []           # [delay, fn, cancelled]

    def __call__(self, delay, fn):
        entry = [delay, fn, False]
        self.pending.append(entry)

        class Handle:
            def cancel(self_):
                entry[2] = True
        return Handle()

    def live(self):
        return [e for e in self.pending if not e[2]]

    def fire_all(self):
        """Run every timer that hasn't been cancelled, as if time passed."""
        due, self.pending = self.live(), []
        for _, fn, _ in due:
            fn()


class FakeClock:
    """Stands in for time.monotonic. Tests move time by setting `now`."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now
