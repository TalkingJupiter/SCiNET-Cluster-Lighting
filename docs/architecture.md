# Architecture

## The pieces

```
front end ──HTTP──▶ api.py ──▶ rack_lights.py ──▶ modes/ ──▶ layout.py
DevOps ────HTTP──▶   │   ▲          │      ▲                    (U → pixels)
                     ▼   │          │      └── meter refresh, every 2 s
                  power.py ─────────┘ one full state per controller
                (latest reading)    ▼
                          clients/wled_client.py ──HTTP──▶ WLED controller
```

| Module | Job | Talks to the network? |
|---|---|---|
| `api.py` | Validates requests, maps errors to HTTP status codes | No (calls `rack_lights`) |
| `engine.py` | Same actions from the command line | No |
| `rack_lights.py` | Remembers what every rack shows, builds each controller's state, runs the hold timers and the meter refresh | Through the client |
| `power.py` | Latest pushed reading per rack; decides when one is stale | No |
| `status.py` | Probes the controllers for `GET /status`, in parallel, cached for 5 s | Through the client |
| `modes/animate.py` | Segments for the idle chase | No |
| `modes/kw_meter.py` | Segments for the kW meter: a reading becomes up to 3 coloured zones per side | No |
| `modes/highlight.py` | Segments for a highlight; enforces the segment budget | No |
| `layout.py` | U numbers → pixel ranges, mirroring for downward sides | No |
| `config_loader.py` | Reads and validates `config.ini` | No |
| `clients/wled_client.py` | Three calls: read the effect list, write state, read info (version, LED count, uptime) | Yes |

Everything below `rack_lights.py` is pure: it takes values and returns
values. That is what lets the whole test suite run without a controller.

## What happens on a highlight

1. The front end sends `POST /racks/Rack1/highlight {"units": [1, 2]}`.
2. `api.py` checks the body is a non-empty list of integers.
3. `rack_lights.highlight()` checks the rack exists and the U's are valid and
   fit the segment budget. **Nothing is sent to the controller until the
   request is known to be good.**
4. Under that controller's lock, it rebuilds the controller's full state:
   for every rack on the controller, either idle segments (chase or meter)
   or highlight segments. Rack1 gets the highlight; its neighbour keeps
   whatever it had.
5. `layout.py` turns U1–U2 into rack pixels 0–5, then places them on each
   side of the rack (mirrored on a side that runs downward).
6. The state goes to WLED as one `POST /json/state`.
7. A timer starts. After `hold-seconds` (5) the rack goes back to idle.

## What happens to a power reading

1. DevOps sends `PUT /racks/Rack1/power` with the token. `api.py` checks
   the token and the body, and `power.py` stores it. Nothing is sent to
   the LEDs yet.
2. Every 2 seconds the meter refresh (a background thread started with the
   API) rebuilds each controller's state under its lock. Idle racks get
   `kw_meter()` segments from the latest reading, or no-data segments if
   there is none or it's older than `stale-after-seconds`. Highlighted
   racks keep their highlight.
3. The new state is compared with the last one the controller accepted. If
   it's the same (the bar didn't change height or colour), nothing is
   sent.

## Design decisions

### WLED JSON API, not DDP

Chase, breathe, and the meter's solid zones and blink are all built into
WLED, so nothing needs streaming. DDP (streaming raw pixels) puts the whole
controller into realtime mode, which would take over both racks on it. The
meter is a few still segments, not an animation, so it doesn't need DDP.

### The whole controller is rewritten on every change

Two racks can share a controller. WLED keeps segments as a packed list: when
a segment is deleted, the ones after it move down. So Rack1 can't own
"segments 8–15" and update only those — deleting one of Rack1's segments
would shift Rack2's segments into Rack1's slots.

Instead, every change rebuilds the controller from what each of its racks
should show, numbers the segments 0, 1, 2… with no gaps, and deletes every
slot above that. The controller never holds leftovers from a previous state.

Every segment also sets every field (`rev`, palette, speed, …) because WLED
keeps a reused slot's old values otherwise.

### The server decides when to go idle

The front end can only ask for highlights. It can't put a rack back to idle,
so a front end that crashes, loses connection or forgets can never leave a
rack lit.

- A highlight holds for `hold-seconds`, then the rack returns to idle.
- A new highlight on the same rack replaces the old one and restarts the
  timer.
- Each highlight gets a generation number. A timer only acts if its
  generation is still the latest, and that check happens under the
  controller lock, so an expiring timer can never clear a highlight that
  arrived at the same moment.
- If returning to idle fails (controller unreachable), it retries every
  `hold-seconds` until it works or a newer request replaces it.
- Timer threads are not daemons: stopping the process waits for pending
  timers, so racks end up chasing rather than stuck on a highlight.

### Effects are looked up by name

Effect IDs change between WLED versions. The config says `Chase` and
`Breathe`; the client reads `/json/eff` once per controller and finds the
IDs.

### State is only updated after the controller accepts it

If a write fails, `rack_lights` keeps its previous record of what the rack
shows. What the process believes and what the LEDs show don't drift apart.

### The meter writes on change, and resends every 60 s

Most refreshes change nothing, so the refresh only writes a controller
whose state differs from the last one it accepted. A failed write isn't
recorded, so it's tried again later.

A controller that loses power comes back with WLED's defaults and has no
way to tell us. So each controller's state is also resent at least every
60 seconds, even if nothing changed. This runs in chase mode too, where
it's the only thing the refresh does.

### Controllers are written in parallel, and dead ones are left alone

Startup and every refresh write all controllers at once, one thread each;
each has its own lock, so they can't interfere. One pass then takes as long
as the slowest controller, not the sum of them all. Done one after another,
six unreachable DNOC controllers at 3 s each made every pass take about 18 s,
so the meter on the live racks updated every 20 s instead of every 2 s.

A controller whose write failed is skipped for 30 seconds (no request, no
timeout) before it's tried again, and a highlight that reaches it ends the
wait early. When it answers again it gets its full state even if nothing
changed on our side, because it has most likely rebooted and lost its
segments.

### Status checks are on demand, cached, and take the controller lock

`GET /status` asks each controller for `/json/info`. The checks run when
`/status` is called, not on a timer, all controllers at once with a 1.5 s
timeout, and the answer is reused for 5 seconds. However often `/status` is
polled, each controller sees at most one small GET every 5 seconds.

The refresh's own failures aren't enough to tell whether a controller is
up: in chase mode it only writes once a minute.

A check takes the controller's lock, like a write. The controllers (ESP32;
an ESP8266 even more so) handle only a few connections at once, and WLED builds every JSON reply in one shared
buffer, answering "busy" to a request that arrives while it's in use. A
check landing in the middle of a highlight could make the highlight fail.
A check that can't get the lock within 1.5 s gives up and reports the
controller unreachable: a write that takes that long is a write to a
controller that isn't answering.

Uptime going down between two checks means the controller rebooted.
`/status` counts it, but doesn't resend anything itself: the 60-second
resend already does that.

## Failure behaviour

| Situation | What happens |
|---|---|
| Controller down at startup | Logged and skipped; the API starts anyway, without waiting on it (controllers are written in parallel). Retried after 30 s |
| Controller down on a highlight | `502`; nothing changes, no timer starts |
| Controller down when a hold expires | Retries every `hold-seconds` |
| Controller down during the meter refresh | Logged once and left alone for 30 s, then retried; the others keep refreshing every 2 s. When it answers again it's logged and rewritten in full |
| Controller rebooted (lost its segments) | Back to the right state within 60 s; `/status` counts it in `reboots` |
| Controller unreachable | `/status` shows it with `last_error` and says `degraded`, or `down` (`503`) if none are reachable; `/health` still answers `200` |
| WLED's LED count differs from the config | `/status` sets `led_count_mismatch` and says `degraded` |
| DevOps stops sending | After `stale-after-seconds` the rack blinks red (meter mode) |
| Bad request | `404`/`422`; nothing is sent to any controller |
| Process stopped during a hold | Waits for the timer, then exits |
| Process killed hard during a hold | The rack stays highlighted until the next start, which sets every rack to idle |
