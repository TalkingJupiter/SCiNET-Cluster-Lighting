# API

```bash
.venv/bin/uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000
```

Interactive docs are served at `/docs` while it runs.

On startup every rack is set to idle: the chase, or the kW meter when
`mode = meter`. A controller that can't be reached is logged and skipped;
the API starts anyway, and a background refresh keeps trying it every
2 seconds.

The front end can only request highlights. **There is no idle endpoint**:
every highlight returns to idle on its own after `hold-seconds`
(5 by default).

| Endpoint | Who calls it | Token |
|---|---|---|
| `POST /racks/{rack}/highlight` | Front end | No |
| `GET /racks` | Anyone | No |
| `PUT /racks/{rack}/power` | DevOps | **Yes** |
| `GET /racks/{rack}/power` | Anyone | No |
| `GET /health` | Docker, systemd, load balancer | No |
| `GET /status` | Monitoring, whoever runs the service | No |

## `POST /racks/{rack}/highlight`

Breathe the given rack units, then return to idle (the chase or the meter).

```json
{"units": [1, 2]}
```

- `units` — list of U numbers, 1 to 42. Order and duplicates don't matter.
- Consecutive U's form one group: `[1, 2, 3]` is one group, `[1, 5]` is two.
- A rack can highlight at most **4 separate groups** at once.
- A new highlight on the same rack replaces the previous one and restarts
  the hold.
- The rest of that rack goes dark. Other racks, including one sharing the
  same controller, are not affected.

**200**

```json
{"rack": "Rack1", "units": [1, 2], "hold_seconds": 5.0}
```

`units` comes back sorted and de-duplicated.

**Errors**

| Status | When | Example `detail` |
|---|---|---|
| `404` | Unknown rack | `unknown rack 'Rack9'; known: Rack1, Rack2, …` |
| `422` | Empty list, not integers, U outside 1–42 | `U43 is outside 1..42` |
| `422` | More than 4 separate groups | `5 separate U groups on 2 sides need 10 segments; Rack1 has 8. At most 4 groups.` |
| `502` | Controller unreachable | `Rack1 controller unreachable: timed out` |

On any error nothing is sent to the controller and no timer starts.

```bash
curl -X POST localhost:8000/racks/Rack1/highlight \
  -H 'content-type: application/json' \
  -d '{"units": [1, 2]}'
```

## `GET /racks`

What every rack is showing right now.

```json
{
  "Rack1": {"showing": [1, 2]},
  "Rack2": {"showing": "idle"}
}
```

This is what the server last sent successfully, not a read-back from the
controller. [`GET /status`](#get-status) says whether the controllers are
actually there.

## Power readings

DevOps pushes each rack's power to the API; the kW meter reads it from
there. The API only **stores** readings: a push never writes to the LEDs
itself. In `meter` mode a background refresh redraws idle racks from the
store every 2 seconds, so a new reading shows within about 2 seconds.

Pushing needs a shared token, `power_ingest_token`, set in `.env` on the
server (see [configuration](configuration.md#env)). Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

and give the same value to DevOps through a password manager, not chat or
email. Reading needs no token.

## `PUT /racks/{rack}/power`

Store the latest power reading for one rack.

```
PUT /racks/Rack1/power
Authorization: Bearer <power_ingest_token>
Content-Type: application/json
```

```json
{"kw": 12.4, "measured_at": "2026-10-27T14:03:02Z"}
```

| Field | Rules |
|---|---|
| `kw` | **Required.** A number ≥ 0, or `null` when there is no data for this rack. Never send `0` to mean "no data": `0` means the rack draws nothing. `Infinity` and `NaN` are rejected. |
| `measured_at` | **Required.** When the reading was taken, as an ISO 8601 timestamp **with a timezone** (`Z` or an offset such as `+02:00`). |

- **Send one request per rack, every 5–10 seconds.** A rack that gets no new
  reading for `stale-after-seconds` (30 by default) is treated as having no
  data.
- **Retrying is safe.** Sending the same reading twice, or an older one
  after a newer one, is accepted (`204`) and ignored. Readings are compared
  by `measured_at` as moments in time, so different timezones are fine.
- **Staleness is measured on the server's clock**, from when the reading
  arrived, so clock differences between machines don't matter.
- The header is compared exactly: `Bearer` with a capital B, one space, then
  the token.

**204** — stored (or ignored as old). No body.

**Errors**

| Status | When | Example `detail` |
|---|---|---|
| `401` | No token is configured on the server | `power ingest is not configured` |
| `401` | `Authorization` header missing or empty | `missing authorization header` |
| `401` | Wrong token, or not in the form `Bearer <token>` | `invalid token` |
| `404` | Unknown rack (checked only after the token) | `unknown rack 'Rack9'` |
| `422` | `kw` missing, negative, not a number, `Infinity` or `NaN`; `measured_at` missing, not a timestamp, or without a timezone | a list of `{"type", "loc", "msg"}`, e.g. `Input should be a finite number` |

The token is checked before the rack name, so a caller without the token
can't use the `404`s to learn which racks exist. Nothing is stored on any
error.

```bash
curl -X PUT localhost:8000/racks/Rack1/power \
  -H "Authorization: Bearer $POWER_INGEST_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"kw": 12.4, "measured_at": "2026-10-27T14:03:02Z"}'
```

## `GET /racks/{rack}/power`

The latest reading the server holds for one rack. No token needed.

**200**

```json
{"rack": "Rack1", "kw": 12.4, "measured_at": "2026-10-27T14:03:02Z", "age_seconds": 3.5}
```

| Field | Meaning |
|---|---|
| `kw` | As sent. `null` either because the reading said `null`, or because there is no current reading |
| `measured_at` | As sent. `null` when there is no current reading |
| `age_seconds` | Seconds since **the server received** the reading. `null` when there is no current reading |

How to tell the cases apart:

| Situation | `kw` | `measured_at` |
|---|---|---|
| Fresh reading | number | timestamp |
| DevOps said there's no data | `null` | timestamp |
| Never received, or stale | `null` | `null` |

**Errors:** `404` for an unknown rack.

```bash
curl localhost:8000/racks/Rack1/power
```

## Health and status

Two questions, two endpoints: is the process up (`/health`), and can it do
its job (`/status`).

## `GET /health`

Liveness check for Docker, systemd or a load balancer.

**200**

```json
{"status": "ok"}
```

It makes no controller calls, so it answers immediately even when every
controller is down. If it doesn't answer, the process is down or stuck.

```bash
curl localhost:8000/health
```

## `GET /status`

Whether each controller can be reached and matches the config, and what
each rack is showing.

**200** (`ok` or `degraded`) or **503** (`down`)

Shortened to two controllers, one of them unreachable:

```json
{
  "status": "degraded",
  "mode": "meter",
  "controllers": {
    "140.221.240.5": {
      "reachable": true,
      "racks": ["Rack1", "Rack2"],
      "wled_version": "0.15.0",
      "led_count": 518,
      "expected_led_count": 518,
      "led_count_mismatch": false,
      "uptime_s": 84211,
      "reboots": 0,
      "last_error": null,
      "checked_at": "2026-11-05T12:00:00Z"
    },
    "140.221.240.9": {
      "reachable": false,
      "racks": ["DNOC646"],
      "wled_version": null,
      "led_count": null,
      "expected_led_count": 259,
      "led_count_mismatch": null,
      "uptime_s": null,
      "reboots": 0,
      "last_error": "timed out",
      "checked_at": "2026-11-05T12:00:00Z"
    }
  },
  "racks": {
    "Rack1": {"showing": [1, 2], "hold_remaining_s": 3.2, "kw": 12.4, "kw_age_s": 4.1},
    "Rack2": {"showing": "idle", "hold_remaining_s": null, "kw": null, "kw_age_s": null}
  }
}
```

| `status` | Meaning | HTTP |
|---|---|---|
| `ok` | Every controller reachable, and every LED count as configured | `200` |
| `degraded` | Some controllers unreachable, or an LED count doesn't match | `200` |
| `down` | No controller reachable | `503` |

A monitor can alert on the `503`; `degraded` is for a person to look at.

**Per controller**

| Field | Meaning |
|---|---|
| `reachable` | It answered `GET /json/info` within 1.5 s |
| `racks` | The racks the config puts on it |
| `wled_version` | WLED's `ver`. `null` if unreachable |
| `led_count` | WLED's `leds.count`: how many LEDs the controller is set up for. `null` if unreachable |
| `expected_led_count` | The end of the last configured side on this controller (518 for two racks, 259 for one) |
| `led_count_mismatch` | `true` if the two differ: the config and the controller disagree, usually a bring-up mistake (wrong LED count in WLED's LED settings, or wrong `side-*` values). `null` if unreachable |
| `uptime_s` | Seconds since the controller booted. `null` if unreachable |
| `reboots` | Reboots noticed since the API started (uptime went down between two checks) |
| `last_error` | Why the last check failed, or `null` |
| `checked_at` | When it was checked (UTC) |

A controller that rebooted has forgotten its segments. Nothing extra is
needed: the background refresh resends every controller's state at least
every 60 seconds, so it is back within a minute. `reboots` just makes it
visible.

**Per rack**

| Field | Meaning |
|---|---|
| `showing` | As in `GET /racks`: highlighted U's, or `"idle"` |
| `hold_remaining_s` | Seconds until a highlight returns to idle. `null` when idle |
| `kw`, `kw_age_s` | As in `GET /racks/{rack}/power`: the current reading and its age. Both `null` when there is no current reading |

**How controllers are checked**

- All controllers are checked at the same time, each with a 1.5 s timeout,
  so a dead controller doesn't make the others wait.
- The result is cached for 5 seconds. Calling `/status` more often doesn't
  reach the controllers more often, and a call that arrives while a check
  is running waits for that check instead of starting another.
- A check waits for any write to the same controller to finish first, so
  the two never overlap. If a write has held the controller for more than
  1.5 s, the controller is reported unreachable.
- So `/status` takes up to about 3 seconds when a controller is down, and
  answers at once from the cache otherwise.

```bash
curl localhost:8000/status
```

## Not yet

- **CORS** is not enabled. A browser page on another origin can't call the
  API until its origin is added.
- **Highlights need no authentication** — anyone who can reach the port can
  highlight racks. Only pushing power readings needs the token.
