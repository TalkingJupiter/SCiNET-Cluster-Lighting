# Hardware

## Strips and controllers

- WS2815 LED strips, driven by WLED controllers (Gledopto, ESP32) over the
  WLED JSON API.
- Each rack has **one uncut strip of 259 LEDs**: up side A, across the top,
  and down side B.
- **Rack1–Rack8** share controllers in pairs, one rack per WLED output.
- **The six DNOC racks** (`DNOC646`, `DNOC2009`, `DNOC2544`, `DNOC4409`,
  `DNOC4545`, `DNOC6706`) each have a controller to themselves.

| Controller | Racks | WLED LED count |
|---|---|---|
| `.5` | Rack1, Rack2 | 518 (output 2 starts at 259) |
| `.6` | Rack3, Rack4 | 518 |
| `.7` | Rack5, Rack6 | 518 |
| `.8` | Rack7, Rack8 | 518 |
| `.9` – `.14` | one DNOC rack each | 259 |

A section in `config.ini` is a rack if it has a `led-ip` or a side, so the
DNOC names work the same as `Rack1` in the API: `/racks/DNOC646/highlight`.

## Rack units and LEDs

LEDs don't line up exactly with rack units, so the server spreads the 42 U's
evenly over each side's LEDs, rounding up. There is no pattern to configure:
a side's length in `config.ini` is all it needs.

On the real racks a side has **109 LEDs** from the bottom of U1 to the top of
U42, so each U gets 3 or 2 LEDs (25 threes, 17 twos), never further than
one LED from where it should be:

| U | LEDs on side A (`up`) | Count |
|---|---|---|
| U1 | 1, 2, 3 | 3 |
| U2 | 4, 5, 6 | 3 |
| U3 | 7, 8 | 2 |
| … | … | … |
| U41 | 105, 106, 107 | 3 |
| U42 | 108, 109 | 2 |

A side of 112 LEDs would give exactly 3, 3, 2, 3, 3, 2…, the pattern the
prototype used. Every side of a rack must have the same length, so a U sits
at the same height on both sides; the config loader checks this.

## Sides

The code works in *rack coordinates* (pixel 0 = the bottom of U1 on a side).
Each side in `config.ini` says where it sits on the controller's strip and
which way it runs. A side that runs `down` is mirrored automatically, so a
highlight lands at the same height on both sides and the chase climbs both
sides together.

Pixels no side claims stay dark.

**The layout in use: one uncut 259-LED strip per rack**

```ini
; first rack on a controller (output 1)    second rack (output 2, +259)
side-a = 1, 109, up                         side-a = 260, 109, up
side-b = 150, 109, down                     side-b = 409, 109, down
```

| LEDs (output 1) | What they are |
|---|---|
| 0 | First LED, hidden; never lights |
| 1–109 | Side A, up: U1 = 1–3, U42 = 108–109 |
| 110–149 | Across the top: 40 LEDs, dark |
| 150–258 | Side B, down: U42 = 150–151, U1 = 256–258 |

Output 2 is numbered after output 1, so the second rack is the same plus
259. Measured on Rack5 (`.7`) on 2026-11-11; see
[measuring a strip](#measuring-a-strip) to check another rack.

The other layouts the code supports:

**Strip cut, side B wired on from the top of side A**

```ini
side-a = 0, 109, up
side-b = 109, 109, down
```

**Strip cut, both sides fed from the bottom**

```ini
side-a = 0, 109, up
side-b = 109, 109, up
```

WS2815 can be cut at every LED. It has 4 pads (V+, DI, BI, GND); 4-pin clip
connectors for 10 mm strip avoid soldering.

## Measuring a strip

How the layout above was found, using WLED directly (no server running). Each
command changes only that controller's LEDs; send `python -m rack_lighting
<rack> idle` afterwards to go back to the chase.

1. **Strip length.** Light up to a guess in one colour and the rest in
   another, then count the LEDs of the second colour at the end of the strip.
   Here LEDs 250–259 were red and 9 lit, so the strip is 259 (0–258):

   ```bash
   curl -X POST http://<ip>/json/state -H 'Content-Type: application/json' -d '{"on":true,"bri":80,"seg":[{"id":0,"start":0,"stop":250,"fx":0,"col":[[0,255,0]]},{"id":1,"start":250,"stop":260,"fx":0,"col":[[255,0,0]]},{"id":2,"stop":0},{"id":3,"stop":0}]}'
   ```

2. **Rough corners.** Light every 10th LED (`"spc":9`) to see roughly where
   each side ends:

   ```bash
   curl -X POST http://<ip>/json/state -H 'Content-Type: application/json' -d '{"on":true,"bri":80,"seg":[{"id":0,"start":0,"stop":259,"grp":1,"spc":9,"fx":0,"col":[[0,255,0]]},{"id":1,"stop":0},{"id":2,"stop":0},{"id":3,"stop":0}]}'
   ```

3. **Exact ends.** Alternate red and green LED by LED around a corner
   (`"spc":1`, the second segment starting one later) and count to the U
   markings on the rails: which LED is the bottom of U1, and which is the top
   of U42:

   ```bash
   curl -X POST http://<ip>/json/state -H 'Content-Type: application/json' -d '{"on":true,"bri":80,"seg":[{"id":0,"start":100,"stop":110,"grp":1,"spc":1,"fx":0,"col":[[255,0,0]]},{"id":1,"start":101,"stop":110,"grp":1,"spc":1,"fx":0,"col":[[0,255,0]]},{"id":2,"stop":0},{"id":3,"stop":0}]}'
   ```

A side starts at its U1 LED and its length is the LEDs from the bottom of U1
to the top of U42.

## Segment budget

WLED draws each effect on a *segment* (a pixel range). The ESP32 controllers
allow 32; the server keeps to `max-segments = 16`, so an ESP8266 would work
too.

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

Set these in each controller's web UI (Config → LED Preferences) before the
first run:

- **LED outputs:** on a paired controller, output 1 starts at 0 with 259
  LEDs and output 2 starts at **259** with 259 LEDs, 518 in total. A DNOC
  controller has one output of 259. Get this wrong and the second rack is
  shifted, or the end of a strip never lights; WLED doesn't report an error.
  `GET /status` flags a controller whose LED count doesn't match the config.
- **Boot preset (recommended):** save the orange chase as a preset and set
  it to apply at boot. After a power cut the server resends its state within
  60 seconds anyway; this covers that minute.

## First bring-up

1. Put the controller's IP in `led-ip` and check it's reachable:
   `curl http://<ip>/json/info`. Its `leds.count` should be 518 (paired)
   or 259 (DNOC).
2. `python -m rack_lighting Rack1 idle` — the chase should climb both sides.
   If one side runs down, flip that side's `up`/`down`.
3. `python -m rack_lighting Rack1 1` — U1 should breathe at the very bottom
   of both sides, at the same height. If not, the side's start is wrong:
   [measure the strip](#measuring-a-strip).
4. `Rack1 42` — the top U should be at the very top of both sides, and a U in
   the middle (`Rack1 21`) next to U21 on the rails. If U's drift as they
   climb, the side's length is wrong.
5. `Rack2 1` and `Rack2 42` — the same on the second rack. If Rack2 is
   shifted, output 2's start in WLED isn't 259.
6. With two racks on one controller, highlight both, then read the state
   back and compare segment `start`/`stop` with what was sent:
   `curl http://<ip>/json/state`. WLED ignores input it doesn't accept
   without reporting an error, so reading back is the only proof.
7. **The meter:** set `mode = meter` in `[Led-Controller]`, run the API and
   push a reading (see [API](api.md#put-racksrackpower)). With no reading
   the rack blinks red; 35 kW should light green up to U25 and amber to U29
   on both sides.

For checking pixel boundaries, `effect = Solid` in `[Highlight]` is easier to
read than a breathe.
