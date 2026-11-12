# Configuration

Settings live in `config/config.ini`. To use a different file, set
`RACK_LIGHTING_CONFIG=/path/to/config.ini`.

The file is validated when it loads. A mistake stops startup with a message
that names the problem, rather than lighting the wrong LEDs.

## Racks — one section per rack

Any section with a `led-ip` or a `side-*` key is a rack, whatever its name:
`[Rack1]`, `[DNOC646]`. The name is what the API uses, e.g.
`POST /racks/DNOC646/highlight`. Settings sections have neither key.

```ini
[Rack1]
led-ip = 10.10.1.1
side-a = 1, 109, up
side-b = 150, 109, down
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

- every rack has a `led-ip` (a section with sides but no `led-ip`, e.g. a
  typo like `led_ip`, stops startup rather than silently losing the rack)
- every rack has at least one side
- every side has at least one LED per U (42)
- all sides of a rack are the same length, so U's line up across sides
- sides of racks on the same controller don't overlap

## `[Led-Controller]`

| Key | Default | Meaning |
|---|---|---|
| `mode` | — | What an idle rack shows: `chase`, or `meter` for the [kW meter](#meter). Highlights work the same in both. |
| `connection-type` | `""` | Read but not used yet. |
| `max-segments` | `16` | WLED segment slots per controller. The ESP32 controllers have 32; 16 is the ESP8266 limit. |
| `segments-per-rack` | `8` | Each rack's share, so one rack's highlight can't take its neighbour's segments. |

Checked at load: racks on a controller × `segments-per-rack` ≤ `max-segments`.

## `[Units]`

| Key | Default | Meaning |
|---|---|---|
| `u-count` | — | Rack units per rack (42). |

The U's are spread evenly over each side's length (3 or 2 LEDs each on a
109-LED side); there is no pattern to set. `pattern` and `first-u-pixel`
are no longer used, and the loader stops with an error if either is still
in the file, so an old config can't silently change where U's land.

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
| `min-kw` | — | Bottom of the meter's scale: at or below this the bar is dark. Whole kW. |
| `max-kw` | — | Top of the scale: at or above this the bar fills the rack. Whole kW. |
| `amber-from-kw` | — | The bar turns amber above this. Whole kW. |
| `red-from-kw` | — | The bar turns red above this. Whole kW. |
| `stale-after-seconds` | `30` | Seconds (fractions allowed, must be > 0). A rack whose last power reading arrived longer ago than this counts as having no data. |

Checked at load: `min-kw` < `amber-from-kw` < `red-from-kw` < `max-kw`,
and `amber-from-kw` > 0.

Power readings are pushed by DevOps through `PUT /racks/{rack}/power`; see
the [API](api.md#put-racksrackpower).

## `[Meter]`

How the kW meter looks when `mode = meter`.

| Key | Default | Meaning |
|---|---|---|
| `brightness` | `255` | Segment brightness for every zone and for no data, 0–255 |
| `green` | — | `R, G, B` of the bar from `min-kw` up to `amber-from-kw` |
| `amber` | — | `R, G, B` from `amber-from-kw` up to `red-from-kw` |
| `red` | — | `R, G, B` from `red-from-kw` up to the reading. Also the no-data colour |
| `no-data-effect` | — | WLED effect name for no data, e.g. `Blink` |
| `no-data-speed` | `128` | Speed of that effect, 0–255 |

The meter is a still bar up the U area of every side of the rack (the
pixels across the top stay dark):

| Situation | The rack shows |
|---|---|
| A reading | A bar from the bottom, its height `kw` on the `min-kw`–`max-kw` scale: green, then amber above `amber-from-kw`, then red above `red-from-kw` |
| 0 kW, or at/below `min-kw` | Dark |
| No reading, a stale one, or DevOps sent `kw: null` | The whole column in `red`, with `no-data-effect` |

Current values: 0–50 kW, amber from 30, red from 40, so on a 109-LED side
amber starts at LED 65 and red at LED 87 (about U26 and U34). Readings are redrawn every
2 seconds; a controller is only written when its bar actually changes.

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
