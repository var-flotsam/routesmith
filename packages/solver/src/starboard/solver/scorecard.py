"""The measures shown for a route, computed once from a driven route."""

from dataclasses import dataclass

from starboard.solver.baseline import DrivenRoute
from starboard.solver.costs import drive_seconds, is_left_turn, is_right_turn, turn_seconds
from starboard.solver.graph import StateGraph


@dataclass(frozen=True, slots=True)
class Scorecard:
    """`drive_time_s` includes turn costs. `dead_head_m` is distance on passes that service
    no stop. `street_passes` counts traversals of a segment in one direction."""

    distance_m: float
    drive_time_s: float
    left_turns: int
    right_turns: int
    u_turns: int
    wrong_side_pickups: int
    dead_head_m: float
    street_passes: int
    stops_serviced: int
    stops_unreachable: int


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
    return Scorecard(
        distance_m=distance,
        drive_time_s=drive_time,
        left_turns=sum(is_left_turn(t) for t in route.transitions),
        right_turns=sum(is_right_turn(t) for t in route.transitions),
        u_turns=sum(t.is_u_turn for t in route.transitions),
        wrong_side_pickups=len(route.wrong_side_stop_ids),
        dead_head_m=dead_head,
        street_passes=len(route.traversals),
        stops_serviced=sum(len(t.serviced_stop_ids) for t in route.traversals),
        stops_unreachable=len(route.unreachable_stop_ids),
    )
