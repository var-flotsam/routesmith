"""The current route as driven: the uploaded stops, in their uploaded order.

From each stop the truck takes the quickest legal path to the next one:
never against a one-way, never through a turn a posted restriction forbids,
and U-turning only where the routing rules allow it. The truck's facing
direction is tracked the whole way, so a stop reached with the cart on the
left is counted as a wrong-side pickup rather than assumed away. Where two
paths cost the same, the one that has the cart on the right wins.

The route starts at the first stop and ends at the last; yard and disposal
legs are added once routes carry them.
"""

import heapq
import itertools
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from starboard.solver.costs import drive_seconds, turn_seconds
from starboard.solver.graph import Direction, Pass, SnappedStop, StateGraph, Transition

# Costs closer than this are equal, so the right-side pass can win the tie.
_COST_TOLERANCE_S = 1e-6
_START = "start"


@dataclass(frozen=True, slots=True)
class RoutingRules:
    """Turn rules for driving between stops. U-turns at dead ends are always allowed."""

    u_turns_at_intersections: bool = False


@dataclass(frozen=True, slots=True)
class Traversal:
    """Driving along one pass from `start_m` to `end_m`, measured in the pass's direction."""

    on_pass: Pass
    start_m: float
    end_m: float
    serviced_stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DrivenRoute:
    """Traversals in driving order; `transitions[i]` joins traversal i to traversal i + 1."""

    traversals: tuple[Traversal, ...]
    transitions: tuple[Transition, ...]
    wrong_side_stop_ids: tuple[str, ...]
    unreachable_stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Leg:
    cost_s: float
    transitions: tuple[Transition, ...]
    target_pass: Pass


class _Router:
    def __init__(self, graph: StateGraph, rules: RoutingRules) -> None:
        self._graph = graph
        self._outgoing: dict[Pass, list[Transition]] = defaultdict(list)
        for transition in graph.transitions:
            if self._allowed(transition, rules):
                self._outgoing[transition.from_pass].append(transition)
        self._passes = frozenset(graph.passes)

    def _allowed(self, transition: Transition, rules: RoutingRules) -> bool:
        if transition.forbidden_by_restriction:
            return False
        if transition.is_u_turn:
            return (
                rules.u_turns_at_intersections or transition.via_node in self._graph.dead_end_nodes
            )
        return True

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

    def leg(self, from_pass: Pass, from_m: float, stop: SnappedStop) -> _Leg | None:
        """The quickest legal way from a point on `from_pass` to servicing `stop`."""
        targets = {p: self.position(p, stop) for p in self.passes_for(stop)}
        best: _Leg | None = None

        def consider(candidate: _Leg) -> None:
            nonlocal best
            if (
                best is None
                or candidate.cost_s < best.cost_s - _COST_TOLERANCE_S
                or (
                    abs(candidate.cost_s - best.cost_s) <= _COST_TOLERANCE_S
                    and candidate.target_pass == stop.required_pass
                )
            ):
                best = candidate

        if from_pass in targets and targets[from_pass] >= from_m:
            consider(_Leg(self.seconds(from_pass, targets[from_pass] - from_m), (), from_pass))

        remaining = self.seconds(from_pass, self.length(from_pass) - from_m)
        order = itertools.count()
        best_cost: dict[Pass, float] = {}
        previous: dict[Pass, tuple[Pass | str, Transition]] = {}
        heap: list[tuple[float, int, Pass]] = []
        for transition in self._outgoing[from_pass]:
            cost = remaining + turn_seconds(transition)
            if cost < best_cost.get(transition.to_pass, float("inf")):
                best_cost[transition.to_pass] = cost
                previous[transition.to_pass] = (_START, transition)
                heapq.heappush(heap, (cost, next(order), transition.to_pass))

        settled: set[Pass] = set()
        while heap:
            cost, _, on_pass = heapq.heappop(heap)
            if on_pass in settled:
                continue
            if best is not None and cost > best.cost_s + _COST_TOLERANCE_S:
                break
            settled.add(on_pass)
            if on_pass in targets:
                path = self._path_to(on_pass, previous)
                consider(_Leg(cost + self.seconds(on_pass, targets[on_pass]), path, on_pass))
            through = cost + self.seconds(on_pass, self.length(on_pass))
            for transition in self._outgoing[on_pass]:
                next_cost = through + turn_seconds(transition)
                if next_cost < best_cost.get(transition.to_pass, float("inf")):
                    best_cost[transition.to_pass] = next_cost
                    previous[transition.to_pass] = (on_pass, transition)
                    heapq.heappush(heap, (next_cost, next(order), transition.to_pass))
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


def build_baseline(
    graph: StateGraph, stops: Sequence[SnappedStop], rules: RoutingRules | None = None
) -> DrivenRoute:
    """Drive `stops` in the order given and record every pass, turn and pickup side."""
    router = _Router(graph, rules or RoutingRules())
    traversals: list[Traversal] = []
    transitions: list[Transition] = []
    wrong_side: list[str] = []
    unreachable: list[str] = []

    remaining = list(stops)
    while remaining and not router.passes_for(remaining[0]):
        unreachable.append(remaining.pop(0).stop_id)
    if not remaining:
        return DrivenRoute((), (), (), tuple(unreachable))

    first = remaining.pop(0)
    legal = router.passes_for(first)
    current_pass = first.required_pass if first.required_pass in legal else legal[0]
    start_m = position = router.position(current_pass, first)
    serviced = [first.stop_id]
    if current_pass != first.required_pass:
        wrong_side.append(first.stop_id)

    for stop in remaining:
        leg = router.leg(current_pass, position, stop)
        if leg is None:
            unreachable.append(stop.stop_id)
            continue
        if leg.target_pass != stop.required_pass:
            wrong_side.append(stop.stop_id)
        target_m = router.position(leg.target_pass, stop)
        if not leg.transitions:
            serviced.append(stop.stop_id)
            position = target_m
            continue
        traversals.append(
            Traversal(current_pass, start_m, router.length(current_pass), tuple(serviced))
        )
        for transition in leg.transitions[:-1]:
            transitions.append(transition)
            traversals.append(
                Traversal(transition.to_pass, 0.0, router.length(transition.to_pass), ())
            )
        transitions.append(leg.transitions[-1])
        current_pass, start_m, position = leg.target_pass, 0.0, target_m
        serviced = [stop.stop_id]

    traversals.append(Traversal(current_pass, start_m, position, tuple(serviced)))
    return DrivenRoute(tuple(traversals), tuple(transitions), tuple(wrong_side), tuple(unreachable))
