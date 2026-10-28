# Configuration

Settings live in `config/config.ini`. To use a different file, set
`RACK_LIGHTING_CONFIG=/path/to/config.ini`.

The file is validated when it loads. A mistake stops startup with a message
that names the problem, rather than lighting the wrong LEDs.

## `[RackN]` — one section per rack

Any section whose name starts with `Rack` is a rack.

```ini
[Rack1]
led-ip = 10.10.1.1
side-a = 0, 113, up
side-b = 113, 113, down
```

| Key | Meaning |
|---|---|
| `led-ip` | WLED controller address. Racks with the same `led-ip` share that controller. |
| `side-*` | One entry per side of the rack: `first pixel, pixel count, up\|down` |

**Sides.** The first pixel is 0-based and counted along the controller's
whole strip. `up` means the side's first pixel is at the bottom of the rack;
`down` means it's at the top. Any strip pixel no side claims stays dark.
See [hardware](hardware.md#sides) for the layouts.

Checked at load:

- every rack has at least one side
- every side is long enough for all 42 U's
- sides of racks on the same controller don't overlap

## `[Led-Controller]`

| Key | Default | Meaning |
|---|---|---|
| `mode` | — | `chase` or `meter`. `meter` is not implemented yet. |
| `connection-type` | `""` | Read but not used yet. |
| `max-segments` | `16` | WLED segment slots per controller. 16 is the ESP8266 limit. |
| `segments-per-rack` | `8` | Each rack's share, so one rack's highlight can't take its neighbour's segments. |

Checked at load: racks on a controller × `segments-per-rack` ≤ `max-segments`.

## `[Units]`

| Key | Default | Meaning |
|---|---|---|
| `u-count` | — | Rack units per rack (42). |
| `pattern` | — | Pixels per U, repeating from U1: `3, 3, 2`. |
| `first-u-pixel` | `0` | Pixel within a side, counted from the bottom, where U1 starts. |

## `[Idle]` and `[Highlight]`

| Key | Meaning |
|---|---|
| `effect` | WLED effect **name**, e.g. `Chase`, `Breathe`, `Solid`. Looked up on the controller. |
| `color` | `R, G, B`, 0–255 each. |
| `brightness` | Segment brightness, 0–255. |
| `speed` | Effect speed, 0–255 (default 128). |
| `intensity` | Effect intensity, 0–255 (default 128). |
| `hold-seconds` | `[Highlight]` only. How long a highlight lasts before the rack returns to idle (default 5, must be > 0). |

Current values: orange chase at speed 160; white breathe at speed 200
(medium-fast), brightness 150, held for 5 seconds.

## `[Energy]`

| Key | Default | Meaning |
|---|---|---|
| `min-kw` | — | Bottom of the kW meter's scale (not used yet) |
| `max-kw` | — | Top of the kW meter's scale (not used yet) |
| `stale-after-seconds` | `30` | Whole seconds. A rack whose last power reading arrived longer ago than this counts as having no data. |

Power readings are pushed by DevOps through `PUT /racks/{rack}/power`; see
the [API](api.md#put-racksrackpower).

## `[Led-config]`

Reserved for the kW meter: pixel ranges for the low/mid/high energy colours.
Read and parsed, not used yet.

Note: `mid` ends at 85 and `high` starts at 88, so pixels 86–87 fall in no
range. Worth fixing when the meter is built.

## `.env`

Secrets live in `.env` at the repo root, which is git-ignored: never commit
it. Copy `.env.example` to start.

| Variable | Meaning |
|---|---|
| `power_ingest_token` | Shared secret DevOps sends as `Authorization: Bearer <token>` to push power readings |

Generate a token with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**If it isn't set** (missing or empty), the API still starts and highlights
work, but every power push is rejected with `401`. Nobody can push without
a token, not even by sending `Bearer None`.

**If it leaks**, generate a new one, update `.env` on the server and on the
DevOps side, and restart the service. The old one stops working at once.
