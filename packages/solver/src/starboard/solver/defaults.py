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


# Pickups and turnarounds (packages/solver)

WRONG_SIDE_PICKUP_TIME = Tunable(
    value=64.0,
    unit="s",
    reason=(
        "Extra time for a cart on the truck's left, which the driver leaves the cab to bring to "
        "the arm. Stated default carried over from the nearest public measurement: in "
        "Rochester, NY, semi-automated collection with tippers timed stops where the operator "
        "walked to the left side of one-way streets to roll out, tip and return carts at 110 s, "
        "against 46.2 s for a normal semi-automated stop, 63.8 s more (D. De Roze, 'Rochester "
        "Gets A Lift From Automation', Waste Age, 1 Oct 1996)."
    ),
    source="https://www.waste360.com/industry-insights/rochester-gets-a-lift-from-automation",
)

CART_SERVICE_TIME = Tunable(
    value=12.0,
    unit="s",
    reason=(
        "Time at the stop to collect one cart with the arm, driving excluded: measured at "
        "11-12 s per residence for automated residual collection (Jaunich et al. 2016, Resources, "
        "Conservation & Recycling 114:92-102)."
    ),
    source="https://doi.org/10.1016/j.resconrec.2016.07.012",
)

PASS_BY_DISTANCE = Tunable(
    value=30.0,
    unit="m",
    reason=(
        "A stop this close behind the truck on the same street was passed moments ago; a "
        "driver working a two-sided house-number list collects it then, rather than looping "
        "round the block. About two house frontages on a compact suburban street."
    ),
)

U_TURN_MAX_STOP_DENSITY = Tunable(
    value=32.0,
    unit="stops/km",
    reason=(
        "A street with fewer stops per km than this (both curbs counted) is too sparse to be a "
        "'residence district' under California Vehicle Code section 515, which starts at 13 "
        "dwellings fronting one side within a quarter mile (32.3 per km); section 22103 "
        "restricts U-turns in residence districts. It is the low-density cut-off for "
        "intersection U-turns, applied to every street that meets at the intersection."
    ),
    source="https://codes.findlaw.com/ca/vehicle-code/veh-sect-515/",
)

U_TURN_DENSITY_WINDOW = Tunable(
    value=402.3,
    unit="m",
    reason=(
        "Shortest length a street's stop density is measured over: the quarter mile of "
        "California Vehicle Code section 515, so a short block's few stops are not read as a "
        "high density."
    ),
    source="https://codes.findlaw.com/ca/vehicle-code/veh-sect-515/",
)


SITE_MAX_DISTANCE = Tunable(
    value=500.0,
    unit="m",
    reason=(
        "A yard or disposal site sits off-street, behind a gate; its nearest street node is "
        "seldom more than a few hundred metres away, so a site farther than this is outside "
        "the fetched network and is refused rather than joined to the wrong street."
    ),
)


# The optimizer (packages/solver)

DISPOSAL_UNLOAD_TIME = Tunable(
    value=960.0,
    unit="s",
    reason=(
        "Time on site per disposal visit, queue, weighing and tipping included: a GPS study of "
        "3,053 transfer-station visits measured a mean of 16 minutes (Steyn 2021, University of "
        "Pretoria, section 3.3.1), matching 16.4 minutes over a year at four stations (Wilson & "
        "Vincent 2008, Waste Management 28(10):1742-1750). The mean, not the median, because "
        "route totals add means."
    ),
    source="https://repository.up.ac.za/handle/2263/81173",
)

SOLVER_SOLUTION_LIMIT = Tunable(
    value=2000.0,
    unit="solutions",
    reason=(
        "OR-Tools stops after this many solutions, so the same input always gives the same "
        "route on any machine (a wall-clock limit would not). Set from the benchmark so a "
        "1,200-stop route finishes well inside three minutes."
    ),
)

SOLVER_TIME_LIMIT = Tunable(
    value=180.0,
    unit="s",
    reason=(
        "Safety ceiling for one route's search, matching the three-minute target in "
        "HANDOFF.md section 2.1; the solution limit normally stops the search first."
    ),
)

LOCAL_SEARCH_MAX_ROUNDS = Tunable(
    value=200.0,
    unit="rounds",
    reason="Most improving moves the 2-opt / or-opt pass makes after OR-Tools; it stops sooner "
    "when no move improves.",
)

SPARE_DISPOSAL_VISITS = Tunable(
    value=2.0,
    unit="visits",
    reason=(
        "Optional disposal visits offered to OR-Tools beyond the fewest the carts need, so an "
        "order whose loads pack less tightly still has a place to unload."
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
