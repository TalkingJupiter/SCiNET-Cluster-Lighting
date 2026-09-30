"""Idle mode: WLED's built-in chase on every side of a rack."""


def effect_id(effects, name):
    """Look an effect up by name. IDs shift between WLED versions; names don't."""
    for i, effect in enumerate(effects):
        if effect.lower() == name.lower():
            return i
    raise ValueError(f"WLED has no effect named {name!r}")


def segment(start, stop, style, effects, reverse=False):
    """A full WLED segment. Every field is set explicitly because WLED keeps
    whatever a reused segment slot had before (a leftover `rev` or palette
    would otherwise leak from one rack's segment into another's)."""
    return {
        "start": start,
        "stop": stop,
        "on": True,
        "rev": reverse,
        "pal": 0,
        "fx": effect_id(effects, style.effect),
        "sx": style.speed,
        "ix": style.intensity,
        "col": [list(style.color), [0, 0, 0]],
        "bri": style.brightness,
    }


def default_animation(cfg, rack, effects):
    """Segments for the idle chase on one rack, one per side.

    Downward sides get `rev`, so the chase climbs both sides together.
    """
    return [
        segment(side.start, side.stop, cfg.idle, effects, reverse=side.reverse)
        for side in rack.sides
    ]
