"""Drive time along segments and the cost of each turn, from `defaults`."""

from starboard.solver import defaults
from starboard.solver.graph import StreetSegment, Transition

_SECONDS_PER_HOUR = 3600.0
_METRES_PER_KM = 1000.0
_RIGHT_ANGLE_DEG = 90.0


def speed_kph(segment: StreetSegment) -> float:
    if segment.speed_limit_kph is not None and segment.speed_limit_kph > 0:
        return segment.speed_limit_kph
    tunable = defaults.ROAD_CLASS_SPEEDS.get(segment.road_class or "", defaults.FALLBACK_SPEED)
    return tunable.value


def drive_seconds(segment: StreetSegment, distance_m: float) -> float:
    """Time to drive `distance_m` of `segment`."""
    return distance_m / _METRES_PER_KM / speed_kph(segment) * _SECONDS_PER_HOUR


def is_left_turn(transition: Transition) -> bool:
    return (
        not transition.is_u_turn and transition.heading_change_deg <= -defaults.TURN_MIN_ANGLE.value
    )


def is_right_turn(transition: Transition) -> bool:
    return (
        not transition.is_u_turn and transition.heading_change_deg >= defaults.TURN_MIN_ANGLE.value
    )


def turn_seconds(transition: Transition) -> float:
    """Time cost of making a transition: scaled for the angle, more for left and U-turns."""
    if transition.is_u_turn:
        return defaults.U_TURN_PENALTY.value
    angle = abs(transition.heading_change_deg)
    cost = defaults.TURN_PENALTY.value * min(angle / _RIGHT_ANGLE_DEG, 1.0)
    if is_left_turn(transition):
        cost += defaults.LEFT_TURN_EXTRA.value
    return cost
