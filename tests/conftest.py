import textwrap

import pytest

from rack_lighting import config_loader

# Same positions as real WLED: Solid = 0, Breathe = 2, Chase = 28.
EFFECTS = ["Solid", "Blink", "Breathe"] + [f"FX{i}" for i in range(3, 28)] + ["Chase"]

# Rack1 and Rack2 share a controller (strips cut, 4 sides on one strip);
# Rack3 has a controller to itself.
BASE_INI = """
[Rack1]
led-ip = 10.0.0.1
redfish-ips = 10.1.0.1, 10.1.0.2
side-a = 0, 113, up
side-b = 113, 113, down

[Rack2]
led-ip = 10.0.0.1
redfish-ips = 10.1.0.3
side-a = 226, 113, up
side-b = 339, 113, down

[Rack3]
led-ip = 10.0.0.3
redfish-ips = 10.1.0.5
side-a = 0, 113, up
side-b = 113, 113, down

[Led-Controller]
mode = chase
max-segments = 16
segments-per-rack = 8

[Units]
u-count = 42
pattern = 3, 3, 2
first-u-pixel = 0

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

[Led-config]
low-energy-pixel-range = 0:65
mid-energy-pixel-range = 66:85
high-energy-pixel-range = 88:113

[Energy]
min-kw = 0
max-kw = 50
"""


class FakeClient:
    """Stands in for WLEDClient: records every state written."""

    def __init__(self, host):
        self.host = host
        self.states = []

    def effects(self):
        return EFFECTS

    def set_state(self, state):
        self.states.append(state)


@pytest.fixture
def write_ini(tmp_path, monkeypatch):
    """Write an ini (BASE_INI with replacements) and load it."""
    monkeypatch.delenv("redfish_username", raising=False)
    monkeypatch.delenv("redfish_password", raising=False)
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
