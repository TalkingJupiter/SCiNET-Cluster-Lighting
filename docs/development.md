# Development

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Tests

```bash
.venv/bin/python -m pytest
```

No controllers are needed. Settings are in `pyproject.toml`.

| File | Covers |
|---|---|
| `test_layout.py` | 3-3-2 pattern, U grouping, side mirroring, parsing `1,2` / `5-8` |
| `test_modes.py` | Chase and highlight segments, the 4-group limit |
| `test_rack_lights.py` | Shared controllers, segment numbering, the hold timer and its races, retries |
| `test_api.py` | Endpoints, status codes, startup |
| `test_config_loader.py` | Every validation rule, and that the real `config.ini` loads |
| `test_wled_client.py` | The HTTP client against a local fake WLED server |

### Test doubles (`tests/conftest.py`)

- **`FakeClient`** — records every state written instead of sending it.
  Has the same effect list positions as real WLED (Solid 0, Breathe 2,
  Chase 28).
- **`FakeTimers`** — replaces the hold timer. Nothing fires until the test
  calls `fire_all()`, so expiry is tested without waiting 5 seconds.
- **`write_ini`** — writes a config (by default two racks sharing one
  controller plus a third on its own) with any key replaced, and loads it.

`RackLights` takes `client_factory` and `schedule` arguments so tests can
pass these in. `create_app(cfg, lights)` does the same for the API.

## Adding a mode

A mode is a function that returns a list of segment dicts for one rack,
without IDs — see `modes/animate.py`. Use `modes.animate.segment()` so every
field is set. `rack_lights.py` decides which mode each rack shows, numbers
the segments and writes the controller.

For the kW meter, the likely shape:

1. `clients/redfish_client.py` — read power for a rack's `redfish-ips`.
2. `modes/kw_meter.py` — power → segments (e.g. one per colour zone per
   side; 3 per side fits the 8-per-rack budget).
3. A poller that updates each idle rack's meter and rewrites its controller
   under the same lock `rack_lights.py` already uses.

## Conventions

- Commit messages follow Conventional Commits: `feat(scope): …`,
  `fix: …`, `refactor: …`, `test: …`, `docs: …`, `chore: …`.
- Never commit `.env`.
