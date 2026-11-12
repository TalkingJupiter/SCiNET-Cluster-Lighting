# Deployment

The service is one Python process (uvicorn serving `rack_lighting.api`) on
a Raspberry Pi on the NOC network. It talks to the WLED controllers over
HTTP, and the front end and DevOps talk to it on port 8000.

```
front end ─┐
           ├──HTTP :8000──▶ Pi: rack_lighting ──HTTP :80──▶ WLED controllers .5 – .14
DevOps ────┘
```

There are two ways to run it:

| | When | What it gives you |
|---|---|---|
| [By hand](#run-it-by-hand) | Bring-up and testing on site | Logs on screen, stop with Ctrl-C |
| [As a systemd service](#run-it-as-a-service) | The event itself | Starts at boot, restarts after a crash |

## What the Pi needs

- **Linux with Python 3.11 or newer.** Raspberry Pi OS Bookworm ships
  3.11. Check with `python3 --version`.
- **A fixed IP address**, so the front end and DevOps know where to find
  it.
- **Network access to every controller.** From the Pi:
  ```bash
  curl http://140.221.240.5/json/info
  ```
  Repeat for each `led-ip` in `config/config.ini` (`.5` to `.14`).
- **Port 8000 reachable** from the front end and from DevOps, if the Pi
  runs a firewall.

## Install

```bash
git clone https://github.com/TalkingJupiter/SCiNET-Cluster-Lighting.git
cd SCiNET-Cluster-Lighting
git checkout v1.0.0            # the latest release; see the GitHub releases page
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Installing a release tag rather than `main` means the Pi runs exactly what
was tested and released, and `config.ini` stays as it was at that release.

**The token.** Create `.env` from the example and set `power_ingest_token`:

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into .env
chmod 600 .env
```

Give the same value to DevOps through a password manager, never chat or
email. Without it the service still runs and highlights work, but every
power push gets a `401` (see [configuration](configuration.md#env)).

**Check the config loads** and lists all 14 racks:

```bash
.venv/bin/python -m rack_lighting
```

A mistake in `config.ini` stops here with a message naming the problem.

**Optional: record what was installed.** `requirements.txt` gives minimum
versions only, so a later install can pull newer ones. Keep a record of the
versions that worked:

```bash
.venv/bin/pip freeze > installed-versions.txt
```

## Run it by hand

Use `tmux` so the service keeps running when your SSH session closes or
your laptop sleeps. **Start it from the checkout directory:** `.env` is read
from the current directory, and started anywhere else the service runs
without the token (every power push gets a `401`, with no other warning).

```bash
tmux new -s lights
cd ~/SCiNET-Cluster-Lighting
.venv/bin/uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000
```

- Detach with `Ctrl-b d`, and come back with `tmux attach -t lights`.
- Stop it with `Ctrl-C` in that window.
- Without tmux, closing the terminal stops the service.

For testing one rack without the API, the command-line tool talks to the
controllers directly (see [hardware](hardware.md#first-bring-up)):

```bash
.venv/bin/python -m rack_lighting Rack1 idle
.venv/bin/python -m rack_lighting Rack1 1,2
```

Don't run the CLI against a controller while the service is running. Both
would write to it, and the service would overwrite the CLI's change within
60 seconds.

## When it stops

Hardware problems don't stop the process. A controller that's down is
logged once, skipped, and retried every 30 seconds without slowing the
others down, and a bad request gets a 4xx response. The process only exits for:

- **A config error at startup.** It exits straight away with a message.
  Fix `config.ini` and start it again.
- **A crash, a kill, or the Pi rebooting or losing power.**

When it stops, the controllers keep showing what they were last sent:

| A rack that was… | Stays… |
|---|---|
| Chasing | Chasing; nothing looks wrong |
| Highlighted | White until the service runs again |
| Showing the meter | Frozen at its last value, not blinking red |

The API is gone too, so the front end's highlights and DevOps' pushes fail.
On a normal stop (`Ctrl-C`, `systemctl stop`) the service first waits for
any highlight still holding (up to 5 seconds) to go back to idle, so no rack
is left white.

Run by hand, **nothing restarts it**. Someone has to notice and start it
again. That's the reason to use systemd for the event.

## Run it as a service

Replace `<user>` with the account that owns the checkout, and fix the paths
if you cloned somewhere other than its home directory.
`/etc/systemd/system/rack-lighting.service`:

```ini
[Unit]
Description=SCinet rack lighting
Wants=network-online.target
After=network-online.target
# A config error would fail on every restart; give up after 5 tries in a
# minute instead of retrying forever.
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=<user>
WorkingDirectory=/home/<user>/SCiNET-Cluster-Lighting
ExecStart=/home/<user>/SCiNET-Cluster-Lighting/.venv/bin/uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`.env` is read from the directory the service starts in, which is why
`WorkingDirectory` must be the checkout. The unit doesn't need the token
itself.

Enable it (start now, and at every boot):

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rack-lighting
```

Day to day:

| To… | Run |
|---|---|
| See if it's running | `systemctl status rack-lighting` |
| Follow the logs | `journalctl -u rack-lighting -f` |
| See today's logs | `journalctl -u rack-lighting --since today` |
| Apply a change to `config.ini` or `.env` | `sudo systemctl restart rack-lighting` |
| Stop it | `sudo systemctl stop rack-lighting` |
| Stop it starting at boot | `sudo systemctl disable rack-lighting` |

Stop the service before running the CLI or `uvicorn` by hand, or the two
will fight over the controllers and port 8000.

If it gave up after 5 failed starts, `systemctl status` shows it as failed.
Fix the cause (usually `config.ini`; the log names it), then:

```bash
sudo systemctl reset-failed rack-lighting
sudo systemctl start rack-lighting
```

## Update

To move to a newer release (replace `v1.0.1` with its tag):

```bash
cd ~/SCiNET-Cluster-Lighting
git fetch --tags
git checkout v1.0.1
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m rack_lighting          # config still loads?
sudo systemctl restart rack-lighting       # or Ctrl-C and start it again by hand
```

If you changed `config.ini` on the Pi, `git checkout` refuses to overwrite
it: commit the change to the repo first (so it's in the next release), or
`git stash` it and re-apply it after.

A restart sets every rack back to idle, so a highlight in progress ends
early.

## Check it's working

From the Pi, or from any machine that can reach it (replace `localhost`):

```bash
curl localhost:8000/health
curl localhost:8000/status
```

- **`/health`** answers `{"status": "ok"}` whenever the process is up. If it
  doesn't answer, the service isn't running.
- **`/status`** checks every controller. Look for:
  - `"status": "ok"`. `degraded` means at least one controller is
    unreachable or reports the wrong LED count; `down` (HTTP 503) means none
    are reachable.
  - `"reachable": false` and `last_error` on a controller that's down.
  - `"led_count_mismatch": true`. WLED's LED count doesn't match
    `config.ini` (expect 518 on a paired controller, 259 on a DNOC one); see
    [hardware](hardware.md#wled-settings).
  - `reboots` going up. That controller lost power and came back; the
    service resends its state within 60 seconds.

See the [API](api.md#get-status) for every field.

## Test scripts

Four scripts in `scripts/` drive a **running** server over HTTP, the way the
front end and DevOps will. They change the real racks, so start the server
first and make sure nobody minds the lights changing. Each takes `--base
http://<host>:8000` for a server other than this machine, and `--help`.

| Script | What it does |
|---|---|
| `scripts/try_api.sh [rack]` | Tries every endpoint once and prints PASS/FAIL: health, status (with each controller's LED count), a U1/U21/U42 highlight, the error cases, and a power push with the token from `.env` |
| `scripts/simulate_highlights.py` | Acts like the front end: sends highlights every few seconds. `--pattern climb` puts the same U on every rack, one higher each step, which checks the U mapping on all racks at once |
| `scripts/simulate_power.py` | Acts like DevOps: pushes changing kW readings (`--pattern wave`, `sweep`, `random` or `steady`). Needs `mode = meter` to show. `--highlights random` adds highlights on top |
| `scripts/simlib.py` | Shared code for the two simulators |

```bash
scripts/try_api.sh Rack3
.venv/bin/python scripts/simulate_highlights.py --racks Rack1,Rack2 --pattern climb --every 1
.venv/bin/python scripts/simulate_power.py --racks Rack1,Rack2 --pattern sweep --highlights random
```

The token is read from `.env` exactly as the server reads it, and never
printed. When `simulate_power.py` stops, the racks go back to blinking red
once the last readings are older than `stale-after-seconds`.

## Go-live checklist

- [ ] Every controller set up as in [hardware: WLED settings](hardware.md#wled-settings), output 2 starting at 259 on the paired ones
- [ ] U1, U21 and U42 in the right place on every rack, the second racks included: `scripts/simulate_highlights.py --pattern climb` ([hardware](hardware.md#first-bring-up))
- [ ] `python -m rack_lighting` lists all 14 racks
- [ ] `/status` is `ok`: every controller reachable, no LED count mismatch
- [ ] `.env` has a real, generated token, not a placeholder like `test` (`chmod 600`), and DevOps has it and [`docs/api.md`](api.md)
- [ ] The front end can reach `http://<pi>:8000`. A browser page served from another origin also needs CORS ([not enabled yet](api.md#not-yet))
- [ ] `mode` chosen in `config.ini`: `chase`, or `meter` once DevOps is pushing readings (otherwise every rack blinks red)
- [ ] Running under systemd and enabled, and survives `sudo reboot`

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Exits at start with a message about `config.ini` | A typo or invalid value; the message names the section and key |
| `address already in use` | Another copy is running: the service, or one in tmux |
| A controller is `reachable: false` | Wrong `led-ip`, controller off, or no route from the Pi; try `curl http://<ip>/json/info` from the Pi |
| `led_count_mismatch: true` | WLED's LED count or output 2's start isn't set as in [hardware](hardware.md#wled-settings) |
| The end of a strip never lights | Same: WLED's LED count is too low |
| Every rack blinks red | `mode = meter` and no readings arriving: DevOps isn't pushing, or they're more than `stale-after-seconds` old |
| Every power push gets `401` | `power_ingest_token` missing from `.env`, the service was started outside the checkout directory so `.env` wasn't read, or DevOps has a different value |
| The front end gets CORS errors in the browser | CORS isn't enabled yet ([API: not yet](api.md#not-yet)) |
