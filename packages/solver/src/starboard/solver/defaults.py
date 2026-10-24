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


def all_tunables() -> dict[str, Tunable]:
    """Every module-level `Tunable` in this file, keyed by name."""
    return {name: value for name, value in globals().items() if isinstance(value, Tunable)}
