"""Shared pieces for the simulator scripts: HTTP, the token, racks, highlights.

Standard library only, plus python-dotenv (already a server dependency) to
read .env exactly as the server does.
"""

import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

U_COUNT = 42
MAX_GROUPS = 4          # segments-per-rack 8 / 2 sides: more is rejected (422)


def request(method, url, body=None, token=None, timeout=5):
    """(status code, parsed JSON or None). Status 0 means no answer."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, None


def detail(body):
    return body.get("detail") if isinstance(body, dict) else None


def read_token():
    from dotenv import dotenv_values
    return dotenv_values(REPO / ".env").get("power_ingest_token") or ""


def racks_to_use(base, wanted):
    """Rack names from --racks, checked against the API; all of them if None.
    Exits with a message if the API doesn't answer or a name is unknown."""
    code, known = request("GET", f"{base}/racks")
    if code != 200:
        sys.exit(f"Nothing answers at {base}/racks (status {code}). Is the server running?")
    if not wanted:
        return list(known)
    racks = [r.strip() for r in wanted.split(",") if r.strip()]
    unknown = [r for r in racks if r not in known]
    if unknown:
        sys.exit(f"Unknown rack(s): {', '.join(unknown)}. Known: {', '.join(known)}")
    return racks


def short(units):
    """[1, 2, 3, 7] -> '1-3,7'"""
    runs, out = [], []
    for u in sorted(units):
        if runs and u == runs[-1][1] + 1:
            runs[-1][1] = u
        else:
            runs.append([u, u])
    for a, b in runs:
        out.append(str(a) if a == b else f"{a}-{b}")
    return ",".join(out)


class Highlights:
    """What to highlight next, as a list of (rack, units) per step.

    random  one random rack, 1-3 separate groups of 1-3 U's (like a person
            clicking machines in the front end)
    climb   the same single U on every rack, one U higher each step: a white
            dot climbing all racks together, to check the U mapping
    sweep   a 3-U band moving up one rack, U1-3 to U40-42, then the next
            rack: one rack lit at a time, to walk the room
    """

    PATTERNS = ("random", "climb", "sweep")

    def __init__(self, racks, pattern, rng=None):
        self.racks = racks
        self.pattern = pattern
        self.rng = rng or random.Random()
        self.step = 0

    def next(self):
        self.step += 1
        return getattr(self, "_" + self.pattern)()

    def _random(self):
        rack = self.rng.choice(self.racks)
        units = set()
        for _ in range(self.rng.randint(1, 3)):
            size = self.rng.randint(1, 3)
            first = self.rng.randint(1, U_COUNT - size + 1)
            units.update(range(first, first + size))
        return [(rack, sorted(units))]

    def _climb(self):
        u = (self.step - 1) % U_COUNT + 1
        return [(rack, [u]) for rack in self.racks]

    def _sweep(self):
        band = 3
        positions = U_COUNT - band + 1          # U1-3 .. U40-42
        i = self.step - 1
        rack = self.racks[(i // positions) % len(self.racks)]
        first = i % positions + 1
        return [(rack, list(range(first, first + band)))]


def send_highlights(base, plan):
    """POST each (rack, units). Returns printable results, problems flagged."""
    out = []
    for rack, units in plan:
        code, body = request("POST", f"{base}/racks/{rack}/highlight", {"units": units})
        if code == 200:
            out.append(f"{rack} U{short(units)}")
        else:
            out.append(f"! {rack} U{short(units)}: {code or 'no answer'} {detail(body) or ''}".strip())
    return out
