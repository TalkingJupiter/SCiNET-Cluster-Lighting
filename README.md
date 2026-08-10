# SCinet NOC Rack Lighting (test script)

Prototype for driving WS2815 strips on the SC26 NOC racks via WLED's JSON API.
This is a **test script**, not the production controller. It exists to validate
the U-to-pixel mapping against real hardware and to check that the highlight and
idle animations look right on the floor.

## What it does

Runs a calibration sweep: highlights every rack unit from U1 to U42 in turn,
three seconds each, then drops the strip back to the idle chase.

Watch the sweep and confirm each highlight lands on the U it claims to. If it
drifts as it climbs, the pixel pattern is wrong.

## Hardware assumptions

| Thing | Value |
|---|---|
| Pixels per rack | 224 (112 per side) |
| Racks per controller | 2 |
| Redundancy | 1 primary + 1 backup controller per rack |
| Pixel pattern per U | 3, 3, 2 repeating |
| Rack origin | `RACK_START`, currently pixel 1 |

The 3-3-2 pattern is the physical reality of the strip: LEDs don't line up
evenly with rack units, so every third U gets two pixels instead of three. Over
42U that comes to 112 pixels, which matches one side of a rack exactly.

## Setup

```bash
pip install wled
python rack_lights.py
```

The script resolves the controller at `wled.local`. Change the hostname in
`main()` if you're pointed at a specific unit.

## The pieces

**`u_range(u_start, u_count=1)`**
Converts a rack U position into `(start, stop)` LED indices, stop exclusive.
Walks the 3-3-2 pattern from the rack origin, so adjacent ranges tile with no
gaps. `u_range(11, 2)` gives you the two units starting at U11.

**`triger(led, u, u_count=1)`**
White breathing highlight on the given U range. This is the "the thing you want
is here" signal.

**`idle(led, start, stop)`**
Orange chase across the strip. Default resting state.

Both write to **segment 1**. Segment 0 is left alone.

## Known issues

Things that are wrong or unfinished, listed so nobody has to rediscover them:

- **`idle()` ignores its arguments.** It takes `start` and `stop` but hardcodes
  0 and 301 in the body. Either wire the parameters through or drop them.
- **301 doesn't match the stated geometry.** The comment says 224 pixels per
  rack, but idle spans 301. One of the two is stale. Worth resolving before
  this gets built on.
- **`triger` is misspelled.** Should be `trigger`.
- **Dead code.** `U_RANGE` and `import time` are unused since `PATTERN` replaced
  the flat-pitch math.
- **Highlight and idle collide.** Both use segment 1, so a highlight overwrites
  idle rather than layering on top of it. For the real thing, idle should live
  on segment 0 and highlights on segment 1, so tearing down a highlight
  (`{"seg": [{"id": 1, "stop": 0}]}`) reveals idle underneath instead of
  needing a re-send.
- **`RACK_START = 1` skips pixel 0.** Verify that's intentional and not an
  off-by-one.
- **No teardown.** The script leaves the strip in idle and exits. Fine for a
  test, but there's no cleanup path if it's interrupted mid-sweep.

## Notes for the real version

- Breathing (`fx: 2`) is harder to read during calibration than solid
  (`fx: 0`), since the dim phase hides the exact pixel boundaries. Use solid
  when checking alignment.
- WLED silently ignores unknown JSON keys and never errors on bad input. When
  something doesn't work, read the segment back with a GET on `/json/state`
  and compare against what you sent.
- Effect and palette IDs shift between WLED versions. Pull the live list from
  `device.effects` rather than trusting hardcoded numbers across a firmware
  upgrade.
- Fail-closed behavior comes from WLED's realtime timeout, which only applies
  to DDP. This script uses the JSON API, so state persists indefinitely after
  the script exits. That's a feature for static highlights and a hazard for
  anything that's supposed to expire.

> NOTICE: Readme file is generated with AI