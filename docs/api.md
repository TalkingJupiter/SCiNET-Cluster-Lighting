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

## Not yet

- **CORS** is not enabled. A browser page on another origin can't call the
  API until its origin is added.
- **Authentication** — anyone who can reach the port can highlight racks.
