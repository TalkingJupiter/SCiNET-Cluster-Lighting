# API

```bash
.venv/bin/uvicorn rack_lighting.api:create_app --factory --host 0.0.0.0 --port 8000
```

Interactive docs are served at `/docs` while it runs.

On startup every rack is set to the idle chase. A controller that can't be
reached is logged and skipped; the API starts anyway.

The front end can only request highlights. **There is no idle endpoint**:
every highlight returns to the chase on its own after `hold-seconds`
(5 by default).

| Endpoint | Who calls it | Token |
|---|---|---|
| `POST /racks/{rack}/highlight` | Front end | No |
| `GET /racks` | Anyone | No |
| `PUT /racks/{rack}/power` | DevOps | **Yes** |
| `GET /racks/{rack}/power` | Anyone | No |

## `POST /racks/{rack}/highlight`

Breathe the given rack units, then return to the chase.

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
controller.

## Power readings

DevOps pushes each rack's power to the API; the kW meter (not built yet)
reads it from there. The API only **stores** readings: a push never writes to
the LEDs.

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

## Not yet

- **CORS** is not enabled. A browser page on another origin can't call the
  API until its origin is added.
- **Highlights need no authentication** — anyone who can reach the port can
  highlight racks. Only pushing power readings needs the token.
