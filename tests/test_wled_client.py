"""WLEDClient against a tiny local HTTP server that behaves like WLED."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from rack_lighting.rack_lights import RackLights
from tests.conftest import EFFECTS, FakeTimers
from rack_lighting.clients.wled_client import WLEDClient


INFO = {"ver": "0.15.0", "leds": {"count": 602}, "uptime": 84211}


class FakeWLED(BaseHTTPRequestHandler):
    posted = []
    gets = []

    def _reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        FakeWLED.gets.append(self.path)
        replies = {"/json/eff": EFFECTS, "/json/info": INFO}
        self._reply(replies.get(self.path, {}))

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        FakeWLED.posted.append((self.path, json.loads(self.rfile.read(length))))
        self._reply({"success": True})

    def log_message(self, *args):
        pass


@pytest.fixture
def wled():
    FakeWLED.posted.clear()
    FakeWLED.gets.clear()
    server = HTTPServer(("127.0.0.1", 0), FakeWLED)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.server_port}"
    server.shutdown()


def test_effects_are_fetched_once(wled):
    client = WLEDClient(wled)
    assert client.effects()[28] == "Chase"
    client.effects()
    assert FakeWLED.gets == ["/json/eff"]


def test_set_state_posts_json(wled):
    WLEDClient(wled).set_state({"on": True})
    assert FakeWLED.posted == [("/json/state", {"on": True})]


def test_info_reads_json_info(wled):
    assert WLEDClient(wled).info() == INFO
    assert FakeWLED.gets == ["/json/info"]


def test_info_takes_its_own_timeout(monkeypatch):
    """A status probe gives up sooner than a write."""
    timeouts = []

    def urlopen(req, timeout):
        timeouts.append((req.full_url, timeout))
        raise OSError("not sending")
    monkeypatch.setattr("rack_lighting.clients.wled_client.urllib.request.urlopen", urlopen)
    client = WLEDClient("wled", timeout=3.0)
    for call in (lambda: client.info(timeout=1.5), client.info, lambda: client.set_state({})):
        with pytest.raises(OSError):
            call()
    assert timeouts == [
        ("http://wled/json/info", 1.5),
        ("http://wled/json/info", 3.0),
        ("http://wled/json/state", 3.0),
    ]


def test_end_to_end_highlight(wled, cfg):
    lights = RackLights(cfg, client_factory=lambda host: WLEDClient(wled), schedule=FakeTimers())
    lights.highlight("Rack1", [1, 2])
    path, state = FakeWLED.posted[-1]
    assert path == "/json/state"
    assert (state["seg"][0]["start"], state["seg"][0]["stop"]) == (0, 6)
    assert state["seg"][0]["fx"] == 2          # Breathe


def test_unreachable_controller_raises(cfg):
    client = WLEDClient("127.0.0.1:1", timeout=0.5)
    with pytest.raises(OSError):
        client.set_state({"on": True})
