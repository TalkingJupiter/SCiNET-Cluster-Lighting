"""Minimal WLED JSON API client (stdlib only).

Only two calls are needed: read the effect list, write state. Anything with
the same two methods can stand in for this, which is how the tests run
without a controller.
"""

import json
import urllib.request


class WLEDClient:
    def __init__(self, host, timeout=3.0):
        self.base = f"http://{host}"
        self.timeout = timeout
        self._effects = None

    def _request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method="GET" if body is None else "POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read() or b"null")

    def effects(self):
        """Effect names; the list index is the effect ID. Cached."""
        if self._effects is None:
            self._effects = self._request("/json/eff")
        return self._effects

    def set_state(self, state):
        return self._request("/json/state", state)
