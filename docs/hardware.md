# Hardware

## Strips and controllers

- WS2815 LED strips, driven by WLED controllers over the WLED JSON API.
- Each rack has **one uncut strip of 301 LEDs**: up side A, across the top,
  and down side B.
- **Rack1–Rack8** share controllers in pairs, one rack per WLED output.
- **The six DNOC racks** (`DNOC646`, `DNOC2009`, `DNOC2544`, `DNOC4409`,
  `DNOC4545`, `DNOC6706`) each have a controller to themselves.

| Controller | Racks | WLED LED count |
|---|---|---|
| `.5` | Rack1, Rack2 | 602 (output 2 starts at 301) |
| `.6` | Rack3, Rack4 | 602 |
| `.7` | Rack5, Rack6 | 602 |
| `.8` | Rack7, Rack8 | 602 |
| `.9` – `.14` | one DNOC rack each | 301 |

A section in `config.ini` is a rack if it has a `led-ip` or a side, so the
DNOC names work the same as `Rack1` in the API: `/racks/DNOC646/highlight`.

## The 3-3-2 pattern

LEDs don't line up evenly with rack units, so U's get 3, 3, 2 pixels,
repeating from U1 at the bottom. Every third U has one pixel fewer. 42U uses
112 pixels; with 113 pixels per side, the top pixel is unused.

| U | Pixels on an `up` side | Count |
|---|---|---|
| U1 | 0, 1, 2 | 3 |
| U2 | 3, 4, 5 | 3 |
| U3 | 6, 7 | 2 |
| U4 | 8, 9, 10 | 3 |
| U5 | 11, 12, 13 | 3 |
| U6 | 14, 15 | 2 |
| … | … | … |
| U42 | 110, 111 | 2 |

If the first LED sits below U1, set `first-u-pixel` to skip it.

## Sides

The code works in *rack coordinates* (pixel 0 = bottom of a side). Each side
in `config.ini` says where it sits on the controller's strip and which way
it runs. A side that runs `down` is mirrored automatically, so a highlight
lands at the same height on both sides and the chase climbs both sides
together.

Pixels no side claims stay dark.

**The layout in use: one uncut 301-LED strip per rack**

```ini
; first rack on a controller (output 1)    second rack (output 2)
side-a = 1, 113, up                         side-a = 302, 113, up
side-b = 188, 113, down                     side-b = 489, 113, down
```

| Pixels (output 1) | What they are |
|---|---|
| 0 | First LED, skipped (as on the calibrated prototype) |
| 1–113 | Side A, up: U1 = 1–3, U42 = 111–112, 113 spare |
| 114–187 | Across the top: 74 LEDs, dark |
| 188–300 | Side B, down: U42 = 189–190, U1 = 298–300, 188 spare |

Output 2 is numbered after output 1, so the second rack is the same plus
301. These numbers come from the prototype's measurements; confirm the
strip length and the dark section on the mounted hardware.

The other layouts the code supports:

**Strip cut, side B wired on from the top of side A**

```ini
side-a = 0, 113, up
side-b = 113, 113, down
```

**Strip not cut — it goes up, across the top, and down.** The LEDs across
the top are unused and stay dark. Measure the gap and start side B after it:

```ini
side-a = 0, 113, up
side-b = 149, 113, down      ; 113–148 cross the top
```

A rack is about 600 mm wide: roughly 36 LEDs at 60 LEDs/m, more at higher
density. An uncut strip therefore needs to be about 2 × 113 + the gap long.

**Strip cut, both sides fed from the bottom**

```ini
side-a = 0, 113, up
side-b = 113, 113, up
```

**Two racks on one controller, cut strips.** The second rack's sides start
after the first rack's:

```ini
[Rack1]                         [Rack2]
led-ip = 10.10.1.1              led-ip = 10.10.1.1
side-a = 0, 113, up             side-a = 226, 113, up
side-b = 113, 113, down         side-b = 339, 113, down
```

WS2815 can be cut at every LED. It has 4 pads (V+, DI, BI, GND); 4-pin clip
connectors for 10 mm strip avoid soldering.

## Segment budget

WLED draws each effect on a *segment* (a pixel range). ESP8266 controllers
allow 16 segments.

Segments are counted for what's showing **now**, not per mode — a highlight
replaces the chase on that rack, it doesn't add to it.

| Rack 1 | Rack 2 | Segments on the controller |
|---|---|---|
| idle | idle | 2 + 2 = 4 |
| highlight `1,2` | idle | 2 + 2 = 4 |
| highlight `1,2` | highlight `20` | 2 + 2 = 4 |
| highlight `1,5,9,20` | highlight `3,7,11,30` | 8 + 8 = 16 |
| meter, red zone reached | highlight `1,5,9,20` | 6 + 8 = 14 |

A highlight costs one segment per side for each separate group of U's. With
8 segments per rack and 2 sides, a rack can highlight 4 separate groups.

## WLED settings

Set these in each controller's web UI before the first run:

- **LED Preferences:** total LED count 602 on a paired controller (output 1:
  301 LEDs starting at 0; output 2: 301 LEDs starting at 301), or 301 on a
  DNOC controller. Too few and the end of the strip never lights; WLED
  doesn't report an error.
- **Max segments:** at least 16 (the ESP8266 limit). The server checks its
  own budget against `max-segments`, not against the controller.
- **Boot preset (recommended):** save the orange chase as a preset and set
  it to apply at boot. After a power cut the server resends its state within
  60 seconds anyway; this covers that minute.

## First bring-up

1. Put the controller's IP in `led-ip` and check it's reachable:
   `curl http://<ip>/json/info`. Its `leds.count` should be 602 (paired)
   or 301 (DNOC).
2. `python -m rack_lighting Rack1 idle` — the chase should climb both sides.
   If one side runs down, flip that side's `up`/`down`.
3. `python -m rack_lighting Rack1 1` — U1 should breathe at the bottom of
   both sides. If it's off by a pixel, adjust `first-u-pixel`.
4. Try `Rack1 42` — the top U. If it drifts as it climbs, the pattern or
   side length is wrong.
5. With two racks on one controller, highlight both, then read the state
   back and compare segment `start`/`stop` with what was sent:
   `curl http://<ip>/json/state`. WLED ignores input it doesn't accept
   without reporting an error, so reading back is the only proof.

6. Check the second rack on the controller (`Rack2 1`): U1 should sit at
   the bottom of Rack2, not at the top of Rack1. If not, output 2's start in
   WLED isn't 301.
7. **The meter:** set `mode = meter` in `[Led-Controller]`, run the API and
   push a reading (see [API](api.md#put-racksrackpower)). With no reading
   the rack blinks red; 35 kW should light green up to about U25 and amber
   to about U29 on both sides.

For checking pixel boundaries, `effect = Solid` in `[Highlight]` is easier to
read than a breathe.
