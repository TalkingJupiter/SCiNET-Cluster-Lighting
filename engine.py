"""Command-line entry point until the front-end API exists.

    python engine.py                  list racks
    python engine.py Rack1 idle       chase on Rack1
    python engine.py all idle         chase on every rack
    python engine.py Rack1 1,2        highlight U1 and U2 on Rack1
    python engine.py Rack1 5-8,12     ranges work too
"""

import argparse

import config_loader
from layout import parse_units
from rack_lights import RackLights


def main(argv=None):
    parser = argparse.ArgumentParser(description="SCinet rack lighting")
    parser.add_argument("rack", nargs="?", help="rack name, or 'all' with idle")
    parser.add_argument("units", nargs="?", help="'idle' or U numbers like 1,2 or 5-8")
    args = parser.parse_args(argv)

    cfg = config_loader.load()

    if not args.rack:
        print(f"[INFO] mode: {cfg.mode}")
        for name, rack in cfg.racks.items():
            print(f"[INFO] {name}: led {rack.led_ip}, redfish {', '.join(rack.redfish_ips)}")
        return 0

    lights = RackLights(cfg)
    try:
        if args.units in (None, "idle"):
            if args.rack == "all":
                lights.idle_all()
            else:
                lights.idle(args.rack)
        else:
            lights.highlight(args.rack, parse_units(args.units))
    except (KeyError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 2
    except OSError as exc:
        print(f"[ERROR] cannot reach the {args.rack} controller: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
