# Hardware

## Strips and controllers

- WS2815 LED strips, driven by WLED controllers over the WLED JSON API.
- Each rack has LEDs up both sides.
- Two racks per controller is the plan. `config.ini` currently has one rack
  per controller as a placeholder until the wiring is decided.

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

**Two racks on one controller.** The second rack's sides start after the
first rack's:

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

A highlight costs one segment per side for each separate group of U's. With
8 segments per rack and 2 sides, a rack can highlight 4 separate groups.

## First bring-up

1. Put the controller's IP in `led-ip` and check it's reachable:
   `curl http://<ip>/json/info`.
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

For checking pixel boundaries, `effect = Solid` in `[Highlight]` is easier to
read than a breathe.
