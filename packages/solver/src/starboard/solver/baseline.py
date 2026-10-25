"""The current route as driven: the uploaded stops, street by street, in list order.

The streets are driven in the order the list gives them. On each street the
truck collects that street's consecutive stops in the order it reaches them,
the way a driver works a list that alternates sides of the street; house-
number order within the street is not followed literally.

Between stops the truck takes the quickest legal way: never against a
one-way, never through a turn a posted restriction forbids, and U-turning
only where the routing rules allow it. Facing direction is tracked the whole
way. A cart reached on the truck's left is a wrong-side pickup: the driver
leaves the cab to bring it to the arm, which costs
`defaults.WRONG_SIDE_PICKUP_TIME`, so the truck goes round to the right side
instead whenever that is quicker. A stop on the stretch the truck has just
driven (the last `defaults.PASS_BY_DISTANCE` of its path, either curb,
across intersections too) is collected as the truck passes it. Where two
choices cost the same, the right side wins, then no driving, then list order.

The route starts at the first stop and ends at the last; yard and disposal
legs are added once routes carry them.
"""

import heapq
import itertools
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from starboard.solver import defaults
from starboard.solver.connections import allowed_transitions
from starboard.solver.costs import drive_seconds, turn_seconds
from starboard.solver.graph import Direction, Pass, SnappedStop, StateGraph, Transition
from starboard.solver.rules import RoutingRules, u_turn_nodes
from starboard.solver.street_names import normalized_street_name

# Costs closer than this are equal, so the tie-breaks decide.
_COST_TOLERANCE_S = 1e-6
# Positions closer than this are the same point; absorbs floating-point error.
_POSITION_TOLERANCE_M = 1e-6
_START = "start"


@dataclass(frozen=True, slots=True)
class Traversal:
    """Driving along one pass from `start_m` to `end_m`, measured in the pass's direction."""

    on_pass: Pass
    start_m: float
    end_m: float
    serviced_stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Pickup:
    """One stop collected at `at_m` along `traversals[traversal_index]`."""

    stop_id: str
    traversal_index: int
    at_m: float
    wrong_side: bool


@dataclass(frozen=True, slots=True)
class DrivenRoute:
    """Traversals in driving order; `transitions[i]` joins traversal i to traversal i + 1.

    `pickups` are in the order the stops were collected. A stop collected in
    passing belongs to the traversal it was passed on, so a traversal's
    `serviced_stop_ids` are the stops collected along it. `u_turn_nodes` are
    the nodes where the routing rules allowed a U-turn.
    """

    traversals: tuple[Traversal, ...]
    transitions: tuple[Transition, ...]
    pickups: tuple[Pickup, ...]
    unreachable_stop_ids: tuple[str, ...]
    u_turn_nodes: frozenset[int] = frozenset()

    @property
    def wrong_side_stop_ids(self) -> tuple[str, ...]:
        return tuple(p.stop_id for p in self.pickups if p.wrong_side)


@dataclass(frozen=True, slots=True)
class _Leg:
    """One way to collect `stops[stop_index]`.

    Either drive `transitions` and stop at `target_m` on `target_pass`, or,
    with `path_index` set and no transitions, collect it where the truck
    already passed it, at `target_m` along `path[path_index]`.
    """

    cost_s: float
    transitions: tuple[Transition, ...]
    target_pass: Pass
    target_m: float
    stop_index: int
    wrong_side: bool
    path_index: int | None = None


def _choice_key(leg: _Leg) -> tuple[int, bool, bool, int]:
    """Cheapest first; among equal costs the right side, then no driving, then list order."""
    return (
        round(leg.cost_s / _COST_TOLERANCE_S),
        leg.wrong_side,
        bool(leg.transitions),
        leg.stop_index,
    )


def _better(candidate: _Leg, best: _Leg | None) -> bool:
    return best is None or _choice_key(candidate) < _choice_key(best)


@dataclass(slots=True)
class _Driven:
    """A traversal of the path so far; the last one's `end_m` grows as the truck moves."""

    on_pass: Pass
    start_m: float
    end_m: float


class _Router:
    def __init__(self, graph: StateGraph, u_turns_at: frozenset[int]) -> None:
        self._graph = graph
        self._outgoing: dict[Pass, list[Transition]] = defaultdict(list)
        for transition in allowed_transitions(graph, u_turns_at):
            self._outgoing[transition.from_pass].append(transition)
        self._passes = frozenset(graph.passes)

    def length(self, on_pass: Pass) -> float:
        return self._graph.segments[on_pass.segment_id].length_m

    def seconds(self, on_pass: Pass, distance_m: float) -> float:
        return drive_seconds(self._graph.segments[on_pass.segment_id], distance_m)

    def position(self, on_pass: Pass, stop: SnappedStop) -> float:
        along = min(max(stop.distance_along_m, 0.0), self.length(on_pass))
        return along if on_pass.direction is Direction.FORWARD else self.length(on_pass) - along

    def passes_for(self, stop: SnappedStop) -> list[Pass]:
        candidates = [Pass(stop.segment_id, d) for d in (Direction.FORWARD, Direction.REVERSE)]
        return [p for p in candidates if p in self._passes]

    def nearest(self, from_pass: Pass, from_m: float, stops: Sequence[SnappedStop]) -> _Leg | None:
        """The quickest legal way from a point on `from_pass` to collecting one of `stops`."""
        targets: dict[Pass, list[tuple[int, float]]] = defaultdict(list)
        for index, stop in enumerate(stops):
            for on_pass in self.passes_for(stop):
                targets[on_pass].append((index, self.position(on_pass, stop)))
        best: _Leg | None = None

        def arrive_on(on_pass: Pass, entry_s: float, path: tuple[Transition, ...]) -> None:
            nonlocal best
            start_m = 0.0 if path else from_m
            for index, at_m in targets.get(on_pass, ()):
                if at_m < start_m:
                    continue
                wrong_side = on_pass != stops[index].required_pass
                cost = entry_s + self.seconds(on_pass, at_m - start_m)
                if wrong_side:
                    cost += defaults.WRONG_SIDE_PICKUP_TIME.value
                candidate = _Leg(cost, path, on_pass, at_m, index, wrong_side)
                if _better(candidate, best):
                    best = candidate

        arrive_on(from_pass, 0.0, ())

        remaining = self.seconds(from_pass, self.length(from_pass) - from_m)
        order = itertools.count()
        best_entry: dict[Pass, float] = {}
        previous: dict[Pass, tuple[Pass | str, Transition]] = {}
        heap: list[tuple[float, int, Pass]] = []

        def push(transition: Transition, entry_s: float, before: Pass | str) -> None:
            if entry_s < best_entry.get(transition.to_pass, float("inf")):
                best_entry[transition.to_pass] = entry_s
                previous[transition.to_pass] = (before, transition)
                heapq.heappush(heap, (entry_s, next(order), transition.to_pass))

        for transition in self._outgoing[from_pass]:
            push(transition, remaining + turn_seconds(transition), _START)

        settled: set[Pass] = set()
        while heap:
            entry_s, _, on_pass = heapq.heappop(heap)
            if on_pass in settled:
                continue
            if best is not None and entry_s > best.cost_s + _COST_TOLERANCE_S:
                break
            settled.add(on_pass)
            if on_pass in targets:
                arrive_on(on_pass, entry_s, self._path_to(on_pass, previous))
            through = entry_s + self.seconds(on_pass, self.length(on_pass))
            for transition in self._outgoing[on_pass]:
                push(transition, through + turn_seconds(transition), on_pass)
        return best

    def passed_recently(self, path: list[_Driven], stops: Sequence[SnappedStop]) -> _Leg | None:
        """The cheapest of `stops` to collect where the truck has just driven past it."""
        best: _Leg | None = None
        window = defaults.PASS_BY_DISTANCE.value
        for path_index in range(len(path) - 1, -1, -1):
            driven = path[path_index]
            reach = max(driven.start_m, driven.end_m - window)
            for index, stop in enumerate(stops):
                if driven.on_pass.segment_id != stop.segment_id:
                    continue
                at_m = self.position(driven.on_pass, stop)
                if (
                    not reach - _POSITION_TOLERANCE_M
                    <= at_m
                    <= driven.end_m + _POSITION_TOLERANCE_M
                ):
                    continue
                wrong_side = driven.on_pass != stop.required_pass
                cost = defaults.WRONG_SIDE_PICKUP_TIME.value if wrong_side else 0.0
                candidate = _Leg(cost, (), driven.on_pass, at_m, index, wrong_side, path_index)
                if _better(candidate, best):
                    best = candidate
            window -= driven.end_m - reach
            if window <= 0:
                break
        return best

    @staticmethod
    def _path_to(
        on_pass: Pass, previous: dict[Pass, tuple[Pass | str, Transition]]
    ) -> tuple[Transition, ...]:
        path: list[Transition] = []
        current: Pass | str = on_pass
        while isinstance(current, Pass):
            before, transition = previous[current]
            path.append(transition)
            current = before
        return tuple(reversed(path))


def street_key(graph: StateGraph, stop: SnappedStop) -> str:
    """The street a stop is listed on, normalised so spellings of one street match.

    It is the street in the stop's address, or the OSM name of the segment it
    snapped to when the address has none; unnamed streets share the empty key.
    """
    return normalized_street_name(stop.street or graph.segments[stop.segment_id].name or "")


def street_runs(graph: StateGraph, stops: Sequence[SnappedStop]) -> list[list[SnappedStop]]:
    """Consecutive stops on the same street, as the list gives them."""
    return [list(run) for _, run in itertools.groupby(stops, key=lambda s: street_key(graph, s))]


def build_baseline(
    graph: StateGraph, stops: Sequence[SnappedStop], rules: RoutingRules | None = None
) -> DrivenRoute:
    """Drive `stops` street by street and record every pass, turn and pickup side."""
    allowed_u_turns = u_turn_nodes(graph, stops, rules or RoutingRules())
    router = _Router(graph, allowed_u_turns)
    path: list[_Driven] = []
    transitions: list[Transition] = []
    pickups: list[Pickup] = []
    unreachable = [s.stop_id for s in stops if not router.passes_for(s)]
    reachable = [s for s in stops if router.passes_for(s)]

    for run in street_runs(graph, reachable):
        if not path:
            first = run.pop(0)
            legal = router.passes_for(first)
            first_pass = first.required_pass if first.required_pass in legal else legal[0]
            at_m = router.position(first_pass, first)
            path.append(_Driven(first_pass, at_m, at_m))
            pickups.append(Pickup(first.stop_id, 0, at_m, first_pass != first.required_pass))
        while run:
            current = path[-1]
            passed = router.passed_recently(path, run)
            leg = router.nearest(current.on_pass, current.end_m, run)
            if passed is not None and (leg is None or not _better(leg, passed)):
                leg = passed
            if leg is None:
                unreachable.extend(s.stop_id for s in run)
                break
            stop = run.pop(leg.stop_index)
            if leg.path_index is not None:
                index = leg.path_index
            elif not leg.transitions:
                current.end_m = leg.target_m
                index = len(path) - 1
            else:
                current.end_m = router.length(current.on_pass)
                for transition in leg.transitions[:-1]:
                    transitions.append(transition)
                    path.append(_Driven(transition.to_pass, 0.0, router.length(transition.to_pass)))
                transitions.append(leg.transitions[-1])
                path.append(_Driven(leg.target_pass, 0.0, leg.target_m))
                index = len(path) - 1
            pickups.append(Pickup(stop.stop_id, index, leg.target_m, leg.wrong_side))

    serviced: dict[int, list[str]] = defaultdict(list)
    for pickup in pickups:
        serviced[pickup.traversal_index].append(pickup.stop_id)
    traversals = tuple(
        Traversal(d.on_pass, d.start_m, d.end_m, tuple(serviced.get(i, ())))
        for i, d in enumerate(path)
    )
    return DrivenRoute(
        traversals, tuple(transitions), tuple(pickups), tuple(unreachable), allowed_u_turns
    )
