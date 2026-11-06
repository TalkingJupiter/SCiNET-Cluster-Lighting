# SCinet Cluster Lighting

[![Tests](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/actions/workflows/tests.yml/badge.svg)](https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

LED lighting for the SCinet NOC racks. Every rack has WS2815 strips up both
sides, driven by WLED controllers. When nothing is happening the racks run
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

Run the tests (no controllers needed):

```bash
.venv/bin/python -m pytest
```

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
  clients/wled_client.py       WLED JSON API client
  modes/
    animate.py                 idle chase
    highlight.py               U highlight
    kw_meter.py                kW meter: reading -> coloured bar
tests/                         pytest suite, runs without hardware
docs/                          detailed documentation
```

## Documentation

| Document | What's in it |
|---|---|
| [Architecture](docs/architecture.md) | How a request becomes LEDs, and why it is built this way |
| [API](docs/api.md) | Endpoints, requests, responses, errors |
| [Configuration](docs/configuration.md) | Every setting in `config.ini` and `.env` |
| [Hardware](docs/hardware.md) | Strips, the 3-3-2 pixel pattern, sides, segment limits, first bring-up |
| [Development](docs/development.md) | Tests, test doubles, adding a mode |

## Status

| Feature | State |
|---|---|
| Idle chase | Done |
| U highlight with 5 s hold | Done |
| HTTP API | Done |
| Power readings pushed by DevOps (`PUT`/`GET /racks/{rack}/power`) | Done; DevOps side not connected yet |
| Tested on a real controller | **Not yet** |
| kW meter (`mode = meter`) | Done; not tried on hardware |
| Which racks share which controller | Decided: 2 racks per controller, one per WLED output |
| Cut or uncut strips | Decided: one uncut 301-LED strip per rack |

## License

[MIT](LICENSE) © 2026 Batuhan Sencer
