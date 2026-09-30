# Architecture

## The pieces

```
front end ──HTTP──▶ api.py ──▶ rack_lights.py ──▶ modes/ ──▶ layout.py
                                   │                            (U → pixels)
                                   │ one full state per controller
                                   ▼
                          clients/wled_client.py ──HTTP──▶ WLED controller
```

| Module | Job | Talks to the network? |
|---|---|---|
| `api.py` | Validates requests, maps errors to HTTP status codes | No (calls `rack_lights`) |
| `engine.py` | Same actions from the command line | No |
| `rack_lights.py` | Remembers what every rack shows, builds each controller's state, runs the hold timers | Through the client |
| `modes/animate.py` | Segments for the idle chase | No |
| `modes/highlight.py` | Segments for a highlight; enforces the segment budget | No |
| `layout.py` | U numbers → pixel ranges, mirroring for downward sides | No |
| `config_loader.py` | Reads and validates `config.ini` | No |
| `clients/wled_client.py` | Two calls: read the effect list, write state | Yes |

Everything below `rack_lights.py` is pure: it takes values and returns
values. That is what lets the whole test suite run without a controller.

## What happens on a highlight

1. The front end sends `POST /racks/Rack1/highlight {"units": [1, 2]}`.
2. `api.py` checks the body is a non-empty list of integers.
3. `rack_lights.highlight()` checks the rack exists and the U's are valid and
   fit the segment budget. **Nothing is sent to the controller until the
   request is known to be good.**
4. Under that controller's lock, it rebuilds the controller's full state:
   for every rack on the controller, either chase segments or highlight
   segments. Rack1 gets the highlight; its neighbour keeps whatever it had.
5. `layout.py` turns U1–U2 into rack pixels 0–5, then places them on each
   side of the rack (mirrored on a side that runs downward).
6. The state goes to WLED as one `POST /json/state`.
7. A timer starts. After `hold-seconds` (5) the rack goes back to the chase.

## Design decisions

### WLED JSON API, not DDP

Chase and a steady breathe are built into WLED, so nothing needs streaming.
DDP (streaming raw pixels) puts the whole controller into realtime mode,
which would take over both racks on it. It may come back for the kW meter.

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

- A highlight holds for `hold-seconds`, then the rack returns to the chase.
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

## Failure behaviour

| Situation | What happens |
|---|---|
| Controller down at startup | Logged and skipped; the API starts anyway |
| Controller down on a highlight | `502`; nothing changes, no timer starts |
| Controller down when a hold expires | Retries every `hold-seconds` |
| Bad request | `404`/`422`; nothing is sent to any controller |
| Process stopped during a hold | Waits for the timer, then exits |
| Process killed hard during a hold | The rack stays highlighted until the next start, which sets every rack to chase |
