import os
import configparser
from dataclasses import dataclass

from dotenv import load_dotenv

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
MODES = ("chase", "meter")


@dataclass(frozen=True)
class Side:
    """One side of a rack on the strip: `count` pixels from `start`.

    `reverse` is True when the side runs top-to-bottom, so rack
    coordinates (0 = bottom) have to be flipped onto the strip.
    """
    name: str
    start: int
    count: int
    reverse: bool

    @property
    def stop(self):
        return self.start + self.count


@dataclass(frozen=True)
class Rack:
    name: str
    led_ip: str
    redfish_ips: tuple
    sides: tuple


@dataclass(frozen=True)
class Style:
    effect: str
    color: tuple
    brightness: int
    speed: int = 128
    intensity: int = 128


@dataclass(frozen=True)
class Config:
    racks: dict
    mode: str
    connection_type: str
    max_segments: int
    segments_per_rack: int
    controllers: dict           # led ip -> rack names, in config order
    u_count: int
    pattern: tuple
    first_u_pixel: int
    idle: Style
    highlight: Style
    min_kw: float
    max_kw: float
    energy_ranges: dict
    redfish_username: str
    redfish_password: str


def _ints(text):
    return tuple(int(x) for x in text.split(","))


def _side(name, text):
    parts = [x.strip() for x in text.split(",")]
    if len(parts) != 3:
        raise ValueError(f"{name}: expected 'start, count, up|down', got {text!r}")
    start, count, direction = int(parts[0]), int(parts[1]), parts[2].lower()
    if direction not in ("up", "down"):
        raise ValueError(f"{name}: direction must be 'up' or 'down', got {direction!r}")
    if start < 0 or count < 1:
        raise ValueError(f"{name}: start must be >= 0 and count >= 1")
    return Side(name, start, count, direction == "down")


def _style(section):
    return Style(
        effect=section["effect"],
        color=_ints(section["color"]),
        brightness=section.getint("brightness", 255),
        speed=section.getint("speed", 128),
        intensity=section.getint("intensity", 128),
    )


def load(path=CONFIG_PATH):
    load_dotenv()
    config = configparser.ConfigParser()
    if not config.read(path):
        raise FileNotFoundError(f"Unable to find config file: {path}")

    units = config["Units"]
    u_count = units.getint("u-count")
    pattern = _ints(units["pattern"])
    first_u_pixel = units.getint("first-u-pixel", 0)
    if not pattern or min(pattern) < 1:
        raise ValueError("pattern must be a list of positive pixel counts")
    used = first_u_pixel + sum(pattern[i % len(pattern)] for i in range(u_count))

    controller = config["Led-Controller"]
    mode = controller["mode"].strip().lower()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    max_segments = controller.getint("max-segments", 16)
    segments_per_rack = controller.getint("segments-per-rack", 8)

    racks = {}
    controllers = {}
    for name in config.sections():
        if not name.startswith("Rack"):
            continue
        section = config[name]
        sides = tuple(
            _side(f"{name} {key}", value)
            for key, value in section.items()
            if key.startswith("side-")
        )
        if not sides:
            raise ValueError(f"{name} needs at least one side-* entry")
        if len(sides) > segments_per_rack:
            raise ValueError(f"{name} has more sides than segments-per-rack")
        for side in sides:
            if used > side.count:
                raise ValueError(
                    f"{side.name} has {side.count} pixels but {u_count}U of "
                    f"{list(pattern)} starting at {first_u_pixel} needs {used}"
                )

        rack = Rack(
            name=name,
            led_ip=section["led-ip"],
            redfish_ips=tuple(ip.strip() for ip in section["redfish-ips"].split(",")),
            sides=sides,
        )
        racks[name] = rack
        controllers.setdefault(rack.led_ip, []).append(name)

    # Racks sharing a controller share its segments and its pixels.
    for ip, names in controllers.items():
        if len(names) * segments_per_rack > max_segments:
            raise ValueError(
                f"controller {ip} has {len(names)} racks x {segments_per_rack} "
                f"segments-per-rack, but only {max_segments} max-segments"
            )
        sides = [side for n in names for side in racks[n].sides]
        for i, a in enumerate(sides):
            for b in sides[i + 1:]:
                if a.start < b.stop and b.start < a.stop:
                    raise ValueError(f"{a.name} and {b.name} overlap on controller {ip}")

    # NOTE: Do we need to keep the low values or can we do it via prev high value?
    energy_ranges = {
        level: _ints(config["Led-config"][f"{level}-energy-pixel-range"].replace(":", ","))
        for level in ("low", "mid", "high")
    }

    redfish_username = os.environ.get("redfish_username")
    redfish_password = os.environ.get("redfish_password")
    if mode == "meter" and not (redfish_username and redfish_password):
        raise RuntimeError("The selected mode is meter but there is no username or password")

    return Config(
        racks=racks,
        mode=mode,
        connection_type=controller.get("connection-type", ""),
        max_segments=max_segments,
        segments_per_rack=segments_per_rack,
        controllers={ip: tuple(names) for ip, names in controllers.items()},
        u_count=u_count,
        pattern=pattern,
        first_u_pixel=first_u_pixel,
        idle=_style(config["Idle"]),
        highlight=_style(config["Highlight"]),
        min_kw=config.getfloat("Energy", "min-kw"),
        max_kw=config.getfloat("Energy", "max-kw"),
        energy_ranges=energy_ranges,
        redfish_username=redfish_username,
        redfish_password=redfish_password,
    )
