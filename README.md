# SCinet Cluster Lighting

LED lighting for the SCinet NOC racks. Every rack has WS2815 strips up both
sides, driven by WLED controllers. When nothing is happening the racks run
an orange chase. When the front end asks about a machine, the rack units
(U's) it lives in breathe white for 5 seconds, then the rack goes back to
the chase on its own.

A kW meter mode, driven by Redfish power readings, is planned but not built
yet.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # only needed for meter mode
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
  rack_lights.py               what each rack shows; the 5 s hold timer
  clients/wled_client.py       WLED JSON API client
  modes/
    animate.py                 idle chase
    highlight.py               U highlight
    kw_meter.py                kW meter (not implemented)
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
| Tested on a real controller | **Not yet** |
| Which racks share which controller | To decide (`config.ini` has one rack per controller as a placeholder) |
| Cut or uncut strips | To decide (sets `side-b`) |
| kW meter from Redfish | Not started |
