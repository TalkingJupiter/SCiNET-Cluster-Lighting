import os
import configparser
from dataclasses import dataclass

from dotenv import load_dotenv

# <repo>/config/config.ini; set RACK_LIGHTING_CONFIG to use another file.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get(
    "RACK_LIGHTING_CONFIG", os.path.join(REPO_ROOT, "config", "config.ini")
)
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
    sides: tuple


@dataclass(frozen=True)
class Style:
    effect: str
    color: tuple
    brightness: int
    speed: int = 128
    intensity: int = 128

@dataclass(frozen=True)
class MeterStyle:
    green: Style
    amber: Style
    red: Style
    no_data: Style

@dataclass(frozen=True)
class Config:
    racks: dict
    mode: str
    connection_type: str
    max_segments: int
    segments_per_rack: int
    controllers: dict           # led ip -> rack names, in config order
    u_count: int
    idle: Style
    highlight: Style
    highlight_hold_s: float     # a highlight returns to idle after this long
    min_kw: float
    max_kw: float
    amber_from_kw: int
    red_from_kw: int
    meter: MeterStyle
    stale_after_seconds: float   # a power reading older than this counts as no data
    power_ingest_token: str | None   # None = power pushes are all rejected


def _ints(text):
    return tuple(int(x) for x in text.split(","))


def _is_rack(section):
    return "led-ip" in section or any(key.startswith("side-") for key in section)


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

def _meterStyle(section):
    green = Style(
        effect="Solid",
        color=_ints(section["green"]),
        brightness=section.getint("brightness", 255),
        speed=section.getint("speed", 128),
        intensity=section.getint("intensity", 128),
    )

    amber = Style(
        effect="Solid",
        color=_ints(section["amber"]),
        brightness=section.getint("brightness", 255),
        speed=section.getint("speed", 128),
        intensity=section.getint("intensity", 128), 
    )

    red = Style(
        effect="Solid",
        color=_ints(section["red"]),
        brightness=section.getint("brightness", 255),
        speed=section.getint("speed", 128),
        intensity=section.getint("intensity", 128), 
    )

    no_data = Style(
        effect=section["no-data-effect"],
        color=_ints(section["red"]),
        brightness=section.getint("brightness", 255),
        speed=section.getint("no-data-speed", 128),
        intensity=section.getint("intensity", 128),  
    )

    return MeterStyle(green, amber, red, no_data)

def load(path=CONFIG_PATH):
    load_dotenv()
    config = configparser.ConfigParser()
    if not config.read(path):
        raise FileNotFoundError(f"Unable to find config file: {path}")

    power_ingest_token = os.environ.get("power_ingest_token") or None
    units = config["Units"]
    u_count = units.getint("u-count")
    if u_count < 1:
        raise ValueError("[Units] u-count must be at least 1")
    for old in ("pattern", "first-u-pixel"):
        # Silently ignoring these would hide that the U mapping changed.
        if old in units:
            raise ValueError(
                f"[Units] {old} is no longer used: U's are spread evenly over "
                f"each side's length. Remove it, and set each side's length to "
                f"the LEDs alongside U1-U{u_count}."
            )

    controller = config["Led-Controller"]

    energy = config["Energy"]
    amber_from_kw = energy.getint("amber-from-kw")
    red_from_kw = energy.getint("red-from-kw")

    min_kw = energy.getint("min-kw")
    max_kw = energy.getint("max-kw")
    if min_kw >= max_kw:
        raise ValueError(f"min-kw({min_kw}) cannot be equal or greater than max-kw({max_kw})")

    if red_from_kw >= max_kw:
        raise ValueError(f"red-from-kw({red_from_kw}) cannot greater than or equal to max-kw({max_kw})")

    if amber_from_kw <= 0 or amber_from_kw <= min_kw:
        raise ValueError(f"amber-from-kw({amber_from_kw}) cannot be less than or equal to 0 or min-kw({min_kw})")

    if amber_from_kw >= red_from_kw:
        raise ValueError(f"amber-from-kw({amber_from_kw}) cannot be greater than or equal to red-from-kw({red_from_kw})")
    
    mode = controller["mode"].strip().lower()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    max_segments = controller.getint("max-segments", 16)
    segments_per_rack = controller.getint("segments-per-rack", 8)
    stale_after_seconds = energy.getfloat("stale-after-seconds", 30.0)
    if stale_after_seconds <= 0:
        raise ValueError("[Energy] stale-after-seconds must be greater than 0")

    racks = {}
    controllers = {}
    for name in config.sections():
        # A rack is any section with a led-ip or a side, whatever it's called
        # (Rack1, DNOC646, ...). Settings sections have neither.
        section = config[name]
        if not _is_rack(section):
            continue
        if "led-ip" not in section:
            raise ValueError(f"{name} has sides but no led-ip")
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
            if side.count < u_count:
                raise ValueError(
                    f"{side.name} has {side.count} pixels; {u_count} U's need "
                    f"at least one each"
                )
        # U's must line up across sides, and modes use one length per rack.
        if len({side.count for side in sides}) > 1:
            raise ValueError(
                f"{name}: all sides must be the same length, got "
                f"{', '.join(f'{s.name} {s.count}' for s in sides)}"
            )

        rack = Rack(
            name=name,
            led_ip=section["led-ip"],
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

    highlight_hold_s = config["Highlight"].getfloat("hold-seconds", 5.0)
    if highlight_hold_s <= 0:
        raise ValueError("[Highlight] hold-seconds must be greater than 0")


    return Config(
        racks=racks,
        mode=mode,
        connection_type=controller.get("connection-type", ""),
        max_segments=max_segments,
        segments_per_rack=segments_per_rack,
        controllers={ip: tuple(names) for ip, names in controllers.items()},
        u_count=u_count,
        idle=_style(config["Idle"]),
        highlight=_style(config["Highlight"]),
        highlight_hold_s=highlight_hold_s,
        min_kw=min_kw,
        max_kw=max_kw,
        amber_from_kw=amber_from_kw,
        red_from_kw=red_from_kw,
        meter=_meterStyle(config["Meter"]),
        stale_after_seconds=stale_after_seconds,
        power_ingest_token=power_ingest_token,
    )
