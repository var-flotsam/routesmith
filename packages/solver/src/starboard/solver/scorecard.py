"""The measures shown for a route, computed once from a driven route."""

from collections.abc import Sequence
from dataclasses import dataclass, fields

from starboard.solver import defaults
from starboard.solver.costs import drive_seconds, is_left_turn, is_right_turn, turn_seconds
from starboard.solver.graph import StateGraph
from starboard.solver.route import DrivenRoute


@dataclass(frozen=True, slots=True)
class Scorecard:
    """The measures for one route.

    `drive_time_s` is time moving, turn costs included. `service_time_s` is
    collecting carts with the arm; `wrong_side_time_s` is the extra for carts
    picked up from the left; `unload_time_s` is time at the disposal site.
    `route_time_s` is all four together.
    `dead_head_m` is distance on passes that service no stop, and
    `street_passes` counts traversals of a segment in one direction.
    """

    distance_m: float
    drive_time_s: float
    service_time_s: float
    wrong_side_time_s: float
    unload_time_s: float
    route_time_s: float
    left_turns: int
    right_turns: int
    u_turns: int
    wrong_side_pickups: int
    dead_head_m: float
    street_passes: int
    stops_serviced: int
    stops_unreachable: int
    disposal_visits: int


def score(graph: StateGraph, route: DrivenRoute) -> Scorecard:
    distance = 0.0
    drive_time = sum(turn_seconds(t) for t in route.transitions)
    dead_head = 0.0
    for traversal in route.traversals:
        length = traversal.end_m - traversal.start_m
        distance += length
        drive_time += drive_seconds(graph.segments[traversal.on_pass.segment_id], length)
        if not traversal.serviced_stop_ids:
            dead_head += length
    stops_serviced = sum(len(t.serviced_stop_ids) for t in route.traversals)
    service_time = stops_serviced * defaults.CART_SERVICE_TIME.value
    wrong_side_time = len(route.wrong_side_stop_ids) * defaults.WRONG_SIDE_PICKUP_TIME.value
    disposal_visits = sum(v.unload for v in route.place_visits)
    unload_time = disposal_visits * defaults.DISPOSAL_UNLOAD_TIME.value
    return Scorecard(
        distance_m=distance,
        drive_time_s=drive_time,
        service_time_s=service_time,
        wrong_side_time_s=wrong_side_time,
        unload_time_s=unload_time,
        route_time_s=drive_time + service_time + wrong_side_time + unload_time,
        left_turns=sum(is_left_turn(t) for t in route.transitions),
        right_turns=sum(is_right_turn(t) for t in route.transitions),
        u_turns=sum(t.is_u_turn for t in route.transitions),
        wrong_side_pickups=len(route.wrong_side_stop_ids),
        dead_head_m=dead_head,
        street_passes=len(route.traversals),
        stops_serviced=stops_serviced,
        stops_unreachable=len(route.unreachable_stop_ids),
        disposal_visits=disposal_visits,
    )


def area_scorecard(cards: Sequence[Scorecard]) -> Scorecard:
    """The measures for several routes in one area: every measure summed over the routes."""
    totals = {f.name: sum(getattr(card, f.name) for card in cards) for f in fields(Scorecard)}
    return Scorecard(**totals)
