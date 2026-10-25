"""Every tunable in Starboard Routing, each with its unit, reason and source.

Code reads values from here and never writes a bare number for a tunable.
`source` is a public link where one exists; `None` marks a stated default
whose reason is the whole justification.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tunable:
    value: float
    unit: str
    reason: str
    source: str | None = None


# Snapping stops to streets (packages/geo)

SNAP_MAX_DISTANCE = Tunable(
    value=80.0,
    unit="m",
    reason=(
        "Address points sit on the building or parcel, usually 10-50 m from the street "
        "centerline in suburban lots; beyond 80 m the nearest street is too often the wrong one, "
        "so the stop goes to review instead."
    ),
)

SNAP_AMBIGUITY_MARGIN = Tunable(
    value=5.0,
    unit="m",
    reason=(
        "If a differently named street is within this much of the nearest one, the point is "
        "about equally close to both (typically a corner lot) and a planner picks the street."
    ),
)

CURB_SIDE_MIN_OFFSET = Tunable(
    value=1.5,
    unit="m",
    reason=(
        "A point closer than this to the centerline is within GPS and digitising error of the "
        "line, so its side of the street cannot be told and it goes to review."
    ),
)


# OSM data (packages/geo)

OSM_EXTRACT_MAX_AGE = Tunable(
    value=30.0,
    unit="days",
    reason=(
        "A downloaded OSM extract older than this is fetched again, so networks follow the "
        "monthly refresh HANDOFF.md section 2.4 asks for."
    ),
)


# Drive time and turn costs (packages/solver)

_OSRM_CAR_PROFILE = "https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua"

ROAD_CLASS_SPEEDS = {
    road_class: Tunable(
        value=speed,
        unit="km/h",
        reason=(
            f"Speed on {road_class} roads where OSM has no maxspeed; OSRM's car profile "
            "default, a published, widely used routing baseline."
        ),
        source=_OSRM_CAR_PROFILE,
    )
    for road_class, speed in (
        ("motorway", 90.0),
        ("motorway_link", 45.0),
        ("trunk", 85.0),
        ("trunk_link", 40.0),
        ("primary", 65.0),
        ("primary_link", 30.0),
        ("secondary", 55.0),
        ("secondary_link", 25.0),
        ("tertiary", 40.0),
        ("tertiary_link", 20.0),
        ("unclassified", 25.0),
        ("residential", 25.0),
        ("living_street", 10.0),
        ("service", 15.0),
    )
}

FALLBACK_SPEED = Tunable(
    value=25.0,
    unit="km/h",
    reason="Speed for a road with no maxspeed and an unlisted class; OSRM's residential default.",
    source=_OSRM_CAR_PROFILE,
)

TURN_PENALTY = Tunable(
    value=7.5,
    unit="s",
    reason=(
        "Time added for a full 90-degree turn, scaled down for gentler turns; OSRM's car "
        "profile turn_penalty."
    ),
    source=_OSRM_CAR_PROFILE,
)

LEFT_TURN_EXTRA = Tunable(
    value=2.0,
    unit="s",
    reason=(
        "Extra time for a left turn, which crosses oncoming traffic in right-hand traffic; "
        "OSRM's car profile oncoming_turn_penalty."
    ),
    source=_OSRM_CAR_PROFILE,
)

U_TURN_PENALTY = Tunable(
    value=20.0,
    unit="s",
    reason="Time added for a U-turn; OSRM's car profile u_turn_penalty.",
    source=_OSRM_CAR_PROFILE,
)

TURN_MIN_ANGLE = Tunable(
    value=30.0,
    unit="degrees",
    reason=(
        "A heading change smaller than this is a bend or a bear, not a turn, and is not counted "
        "as a left or right turn on the scorecard."
    ),
)


def all_tunables() -> dict[str, Tunable]:
    """Every module-level `Tunable` in this file, keyed by name."""
    found: dict[str, Tunable] = {}
    for name, value in globals().items():
        if isinstance(value, Tunable):
            found[name] = value
        elif isinstance(value, dict):
            found.update(
                {f"{name}[{key}]": item for key, item in value.items() if isinstance(item, Tunable)}
            )
    return found
