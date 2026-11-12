# SCinet Cluster Lighting

[![Tests](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/actions/workflows/tests.yml/badge.svg)](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

LED lighting for the SCinet NOC racks (Rack1–Rack8 and six DNOC racks).
Every rack has a WS2815 strip up both sides, driven by WLED controllers. When nothing is happening the racks run
an orange chase. When the front end asks about a machine, the rack units
(U's) it lives in breathe white for 5 seconds, then the rack goes back to
the chase on its own.

DevOps pushes each rack's power reading to the API. In `meter` mode an idle
rack shows it as a kW meter instead of the chase: a bar up the rack, green,
then amber, then red as power rises, and blinking red when there's no data.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then set power_ingest_token
```

Check the configuration loads and list the racks:

```bash
.venv/bin/python -m rack_lighting
```

Highlight U1 and U2 on Rack1 from the command line (useful on hardware):

```bash
.venv/bin/python -m rack_lighting Rack1 1,2
```

Run the API for the front end:

```bash
.venv/bin/uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000
```

```bash
curl -X POST localhost:8000/racks/Rack1/highlight -H 'content-type: application/json' -d '{"units": [1, 2]}'
```

Try a running server, real racks included (see [test scripts](docs/deployment.md#test-scripts)):

```bash
scripts/try_api.sh Rack3
```

Run the tests (no controllers needed):

```bash
.venv/bin/python -m pytest
```

On the Pi, install a [release](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/releases)
(`git checkout v1.0.0`) rather than `main`; see [deployment](docs/deployment.md).

## Project layout

```
config/config.ini              racks, LED layout, effects, timings
rack_lighting/
  api.py                       HTTP API for the front end
  engine.py                    command-line tool for hardware testing
  __main__.py                  python -m rack_lighting
  config_loader.py             reads and validates config.ini
  layout.py                    rack unit -> LED pixel mapping
  rack_lights.py               what each rack shows; hold timer; meter refresh
  power.py                     latest pushed power reading per rack
  status.py                    controller checks for GET /status
  clients/wled_client.py       WLED JSON API client
  modes/
    animate.py                 idle chase
    highlight.py               U highlight
    kw_meter.py                kW meter: reading -> coloured bar
tests/                         pytest suite, runs without hardware
scripts/                       try a running server; simulate the front end and DevOps
docs/                          detailed documentation
```

## Documentation

| Document | What's in it |
|---|---|
| [Architecture](docs/architecture.md) | How a request becomes LEDs, and why it is built this way |
| [API](docs/api.md) | Endpoints, requests, responses, errors |
| [Configuration](docs/configuration.md) | Every setting in `config.ini` and `.env` |
| [Hardware](docs/hardware.md) | Strips, how U's map to LEDs, sides, measuring a strip, segment limits, WLED settings, first bring-up |
| [Deployment](docs/deployment.md) | Installing on the Pi, running by hand or under systemd, checking it works, go-live checklist |
| [Development](docs/development.md) | Tests, test doubles, adding a mode |

## Status

Latest release: [v1.0.0](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/releases/tag/v1.0.0).

| Feature | State |
|---|---|
| Idle chase | Done; tested on Rack1–8 |
| U highlight with 5 s hold | Done; tested on Rack1–8 |
| HTTP API, `/health`, `/status` | Done; all endpoints tested against the real controllers (`scripts/try_api.sh`) |
| Power readings pushed by DevOps (`PUT`/`GET /racks/{rack}/power`) | Done; DevOps doesn't have the token yet, so no real readings arrive |
| kW meter | Done and tested on the racks with simulated readings, but **off**: `config.ini` has `mode = chase`. Switch once DevOps is sending readings |
| Layout | Measured on Rack5: one uncut 259-LED strip per rack, 109 LEDs per side ([hardware](docs/hardware.md)). U1/U21/U42 checked on Rack1–8 with WLED's old 300 + 300 outputs |
| Second racks (Rack2/4/6/8) at +259 | **To check** after WLED's outputs were changed on site: `/status` reports 520 LEDs, the config expects 518. Confirm output 2 starts at 259 ([hardware: WLED settings](docs/hardware.md#wled-settings)) |
| DNOC racks | In `config.ini` with the same layout; **not measured**, controllers not reachable yet |
| Running on the Pi | Documented ([deployment](docs/deployment.md)); no Pi yet |
| How a highlight ends (#13) | To decide: auto-return (built), solid phase, or kiosk reset |

Known gaps: highlights need no authentication and CORS is not enabled (see
[API](docs/api.md#not-yet)); both are fine on the NOC network but CORS is
needed before a browser front end on another origin can call the API.

## License

[MIT](LICENSE) © 2026 Batuhan Sencer
