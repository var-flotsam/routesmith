"""A driven route as steps a driver can follow: turn, street, how far, which carts.

Consecutive passes along one street with no turn between them are one step. A turn
(`costs.is_left_turn`, `costs.is_right_turn`), a U-turn, or a change of street starts
a new step; so does every visit to the disposal site, which is a step of its own.
Every cart is collected from the right, so the steps name no curb.
"""

from dataclasses import dataclass
from enum import StrEnum

from starboard.solver.costs import is_left_turn, is_right_turn
from starboard.solver.graph import StateGraph, Transition
from starboard.solver.route import DrivenRoute, PlaceVisit
from starboard.solver.street_names import same_street_name


class Action(StrEnum):
    DEPART = "depart"  # leave the yard, or the disposal site after unloading
    LEFT = "left"
    RIGHT = "right"
    STRAIGHT = "straight"  # carry on into a street with another name
    U_TURN = "u_turn"
    UNLOAD = "unload"  # at the disposal site
    ARRIVE = "arrive"  # back at the yard


@dataclass(frozen=True, slots=True)
class Step:
    action: Action
    street: str | None  # None for unnamed roads and for the unload and arrive steps
    distance_m: float
    stop_ids: tuple[str, ...]  # carts collected along this step, in order


def _same_street(first: str | None, second: str | None) -> bool:
    """Two unnamed roads in a row read as one; a named and an unnamed one do not."""
    if first is None or second is None:
        return first is None and second is None
    return same_street_name(first, second)


def _action(transition: Transition) -> Action:
    if transition.is_u_turn:
        return Action.U_TURN
    if is_left_turn(transition):
        return Action.LEFT
    if is_right_turn(transition):
        return Action.RIGHT
    return Action.STRAIGHT


def route_sheet(graph: StateGraph, route: DrivenRoute) -> list[Step]:
    """The route's steps, from leaving the yard to arriving back."""
    if not route.traversals:
        return []
    steps: list[Step] = []
    action, street, distance, stops = Action.DEPART, None, 0.0, list[str]()

    def close() -> None:
        steps.append(Step(action, street, round(distance, 1), tuple(stops)))

    for k, traversal in enumerate(route.traversals):
        name = graph.segments[traversal.on_pass.segment_id].name
        if k == 0:
            street = name
        else:
            join = route.joins[k - 1]
            if isinstance(join, PlaceVisit):
                close()
                if join.unload:
                    steps.append(Step(Action.UNLOAD, None, 0.0, ()))
                action, street, distance, stops = Action.DEPART, name, 0.0, []
            else:
                turn = _action(join)
                if turn is not Action.STRAIGHT or not _same_street(street, name):
                    close()
                    action, street, distance, stops = turn, name, 0.0, []
        distance += traversal.end_m - traversal.start_m
        stops.extend(traversal.serviced_stop_ids)
    close()
    steps.extend(Step(Action.UNLOAD, None, 0.0, ()) for v in route.closing_visits if v.unload)
    steps.append(Step(Action.ARRIVE, None, 0.0, ()))
    return steps
