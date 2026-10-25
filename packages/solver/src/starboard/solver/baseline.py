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

With route sites, the truck leaves the yard, drives to the disposal site
whenever the next cart would overfill it and once more at the end, and
returns to the yard, the same legs the optimized route drives. Without
them the route starts at the first stop and ends at the last.
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
from starboard.solver.route import (
    DrivenRoute,
    Join,
    Pickup,
    PlaceVisit,
    RouteSites,
    Traversal,
    TruckProfile,
)
from starboard.solver.rules import RoutingRules, u_turn_nodes
from starboard.solver.street_names import normalized_street_name

# Costs closer than this are equal, so the tie-breaks decide.
_COST_TOLERANCE_S = 1e-6
# Positions closer than this are the same point; absorbs floating-point error.
_POSITION_TOLERANCE_M = 1e-6


@dataclass(frozen=True, slots=True)
class _Leg:
    """One way to reach `target_m` on `target_pass`, collecting `stops[stop_index]` there.

    The truck drives `transitions`, starting from `origin` (the pass it starts on
    when leaving a place) or from where it is. With `path_index` set and no
    transitions, the stop is collected where the truck already passed it, along
    `path[path_index]`.
    """

    cost_s: float
    transitions: tuple[Transition, ...]
    target_pass: Pass
    target_m: float
    stop_index: int
    wrong_side: bool
    path_index: int | None = None
    origin: Pass | None = None


def _choice_key(leg: _Leg) -> tuple[int, bool, bool, int]:
    """Cheapest first; among equal costs the right side, then no driving, then list order."""
    return (
        round(leg.cost_s / _COST_TOLERANCE_S),
        leg.wrong_side,
        bool(leg.transitions) or leg.origin is not None,
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


@dataclass(frozen=True, slots=True)
class _Seed:
    """Where a search starts: on `on_pass` at `at_m`, having spent `cost_s` already."""

    on_pass: Pass
    at_m: float
    cost_s: float
    from_place: bool


class _Router:
    def __init__(self, graph: StateGraph, u_turns_at: frozenset[int]) -> None:
        self._graph = graph
        self._outgoing: dict[Pass, list[Transition]] = defaultdict(list)
        for transition in allowed_transitions(graph, u_turns_at):
            self._outgoing[transition.from_pass].append(transition)
        self._passes = frozenset(graph.passes)
        self._starting_at: dict[int, list[Pass]] = defaultdict(list)
        self._ending_at: dict[int, list[Pass]] = defaultdict(list)
        for p in sorted(graph.passes, key=lambda q: (q.segment_id, q.direction.value)):
            start, end = self.ends(p)
            self._starting_at[start].append(p)
            self._ending_at[end].append(p)
        self._usable: frozenset[Pass] = self._passes

    def keep_within_reach_of(self, node: int) -> None:
        """Use only passes from which `node` can still be reached, so the truck is never
        trapped short of the disposal site."""
        incoming: dict[Pass, list[Pass]] = defaultdict(list)
        for from_pass, transitions in self._outgoing.items():
            for t in transitions:
                incoming[t.to_pass].append(from_pass)
        reach = set(self._ending_at[node])
        frontier = list(reach)
        while frontier:
            for before in incoming[frontier.pop()]:
                if before not in reach:
                    reach.add(before)
                    frontier.append(before)
        self._usable = frozenset(reach)

    def ends(self, on_pass: Pass) -> tuple[int, int]:
        segment = self._graph.segments[on_pass.segment_id]
        if on_pass.direction is Direction.FORWARD:
            return segment.from_node, segment.to_node
        return segment.to_node, segment.from_node

    def length(self, on_pass: Pass) -> float:
        return self._graph.segments[on_pass.segment_id].length_m

    def seconds(self, on_pass: Pass, distance_m: float) -> float:
        return drive_seconds(self._graph.segments[on_pass.segment_id], distance_m)

    def position(self, on_pass: Pass, stop: SnappedStop) -> float:
        along = min(max(stop.distance_along_m, 0.0), self.length(on_pass))
        return along if on_pass.direction is Direction.FORWARD else self.length(on_pass) - along

    def passes_for(self, stop: SnappedStop) -> list[Pass]:
        candidates = [Pass(stop.segment_id, d) for d in (Direction.FORWARD, Direction.REVERSE)]
        return [p for p in candidates if p in self._usable]

    def seeds_at(self, node: int) -> list[_Seed]:
        """Leaving a place at `node`: the start of every pass that begins there."""
        return [_Seed(p, 0.0, 0.0, True) for p in self._starting_at[node] if p in self._usable]

    def nearest(self, seeds: Sequence[_Seed], stops: Sequence[SnappedStop]) -> _Leg | None:
        """The quickest legal way from `seeds` to collecting one of `stops`."""
        targets: dict[Pass, list[tuple[int, float, bool]]] = defaultdict(list)
        for index, stop in enumerate(stops):
            for on_pass in self.passes_for(stop):
                wrong_side = on_pass != stop.required_pass
                targets[on_pass].append((index, self.position(on_pass, stop), wrong_side))
        return self._search(seeds, targets)

    def to_node(self, seeds: Sequence[_Seed], node: int) -> _Leg | None:
        """The quickest legal way from `seeds` to the end of a pass that ends at `node`."""
        targets = {p: [(0, self.length(p), False)] for p in self._ending_at[node]}
        return self._search(seeds, targets)

    def _search(
        self, seeds: Sequence[_Seed], targets: dict[Pass, list[tuple[int, float, bool]]]
    ) -> _Leg | None:
        best: _Leg | None = None

        def arrive(
            on_pass: Pass,
            start_m: float,
            entry_s: float,
            route: tuple[tuple[Transition, ...], Pass | None],
        ) -> None:
            nonlocal best
            path, origin = route
            for index, at_m, wrong_side in targets.get(on_pass, ()):
                if at_m < start_m - _POSITION_TOLERANCE_M:
                    continue
                cost = entry_s + self.seconds(on_pass, max(at_m - start_m, 0.0))
                if wrong_side:
                    cost += defaults.WRONG_SIDE_PICKUP_TIME.value
                candidate = _Leg(cost, path, on_pass, at_m, index, wrong_side, origin=origin)
                if _better(candidate, best):
                    best = candidate

        order = itertools.count()
        best_entry: dict[Pass, float] = {}
        previous: dict[Pass, tuple[Pass | _Seed, Transition | None]] = {}
        heap: list[tuple[float, int, Pass]] = []

        def push(
            on_pass: Pass, entry_s: float, before: Pass | _Seed, via: Transition | None
        ) -> None:
            if on_pass in self._usable and entry_s < best_entry.get(on_pass, float("inf")):
                best_entry[on_pass] = entry_s
                previous[on_pass] = (before, via)
                heapq.heappush(heap, (entry_s, next(order), on_pass))

        for seed in seeds:
            if seed.from_place:
                push(seed.on_pass, seed.cost_s, seed, None)
                continue
            arrive(seed.on_pass, seed.at_m, seed.cost_s, ((), None))
            through = seed.cost_s + self.seconds(
                seed.on_pass, self.length(seed.on_pass) - seed.at_m
            )
            for transition in self._outgoing[seed.on_pass]:
                push(transition.to_pass, through + turn_seconds(transition), seed, transition)

        settled: set[Pass] = set()
        while heap:
            entry_s, _, on_pass = heapq.heappop(heap)
            if on_pass in settled:
                continue
            if best is not None and entry_s > best.cost_s + _COST_TOLERANCE_S:
                break
            settled.add(on_pass)
            if on_pass in targets:
                arrive(on_pass, 0.0, entry_s, self._route_to(on_pass, previous))
            through = entry_s + self.seconds(on_pass, self.length(on_pass))
            for transition in self._outgoing[on_pass]:
                push(transition.to_pass, through + turn_seconds(transition), on_pass, transition)
        return best

    @staticmethod
    def _route_to(
        on_pass: Pass, previous: dict[Pass, tuple[Pass | _Seed, Transition | None]]
    ) -> tuple[tuple[Transition, ...], Pass | None]:
        """The transitions driven to enter `on_pass`, and the pass left a place on, if any."""
        path: list[Transition] = []
        current: Pass | _Seed = on_pass
        while isinstance(current, Pass):
            before, transition = previous[current]
            if transition is None:  # entered straight from a place
                assert isinstance(before, _Seed)
                return tuple(reversed(path)), before.on_pass
            path.append(transition)
            current = before
        return tuple(reversed(path)), None

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


def street_key(graph: StateGraph, stop: SnappedStop) -> str:
    """The street a stop is listed on, normalised so spellings of one street match.

    It is the street in the stop's address, or the OSM name of the segment it
    snapped to when the address has none; unnamed streets share the empty key.
    """
    return normalized_street_name(stop.street or graph.segments[stop.segment_id].name or "")


def street_runs(graph: StateGraph, stops: Sequence[SnappedStop]) -> list[list[SnappedStop]]:
    """Consecutive stops on the same street, as the list gives them."""
    return [list(run) for _, run in itertools.groupby(stops, key=lambda s: street_key(graph, s))]


class _Drive:
    """The truck's path so far, and where it is: on a pass, or at a place node.

    `pending` are the visits made since the last traversal; the next pass
    driven joins on through the last of them, and any left at the end are the
    route's closing visits.
    """

    def __init__(self, router: _Router) -> None:
        self.router = router
        self.path: list[_Driven] = []
        self.joins: list[Join] = []
        self.pickups: list[Pickup] = []
        self.at_node: int | None = None
        self.pending: list[PlaceVisit] = []
        self.load = 0

    def seeds(self) -> list[_Seed]:
        if self.at_node is not None:
            return self.router.seeds_at(self.at_node)
        current = self.path[-1]
        return [_Seed(current.on_pass, current.end_m, 0.0, False)]

    def take(self, leg: _Leg) -> int:
        """Drive `leg` and return the index of the traversal it ends on."""
        router = self.router
        if leg.path_index is not None:
            return leg.path_index
        if leg.origin is not None:
            if self.path:
                assert len(self.pending) == 1, "one visit joins two passes"
                self.joins.append(self.pending.pop())
            self.pending.clear()
            self.path.append(_Driven(leg.origin, 0.0, router.length(leg.origin)))
            self.at_node = None
        elif leg.transitions:
            self.path[-1].end_m = router.length(self.path[-1].on_pass)
        for transition in leg.transitions:
            self.joins.append(transition)
            self.path.append(_Driven(transition.to_pass, 0.0, router.length(transition.to_pass)))
        self.path[-1].end_m = leg.target_m
        return len(self.path) - 1

    def collect(self, stop: SnappedStop, leg: _Leg) -> None:
        index = self.take(leg)
        self.pickups.append(Pickup(stop.stop_id, index, leg.target_m, leg.wrong_side))
        self.load += 1

    def visit(self, place_visit: PlaceVisit) -> bool:
        """Drive to the place and visit it; False if it cannot be reached."""
        node = place_visit.place.node
        if self.at_node != node:
            leg = self.router.to_node(self.seeds(), node)
            if leg is None:
                return False
            self.take(leg)
            self.at_node = node
        self.pending.append(place_visit)
        return True


def build_baseline(
    graph: StateGraph,
    stops: Sequence[SnappedStop],
    rules: RoutingRules | None = None,
    sites: RouteSites | None = None,
    profile: TruckProfile | None = None,
) -> DrivenRoute:
    """Drive `stops` street by street and record every pass, turn and pickup side."""
    allowed_u_turns = u_turn_nodes(graph, stops, rules or RoutingRules())
    router = _Router(graph, allowed_u_turns)
    drive = _Drive(router)
    capacity = (profile or TruckProfile()).capacity_carts
    if sites is not None:
        router.keep_within_reach_of(sites.disposal.node)
        drive.at_node = sites.yard.node
    unreachable = [s.stop_id for s in stops if not router.passes_for(s)]
    reachable = [s for s in stops if router.passes_for(s)]

    for run in street_runs(graph, reachable):
        if not drive.path and drive.at_node is None:
            first = run.pop(0)
            legal = router.passes_for(first)
            first_pass = first.required_pass if first.required_pass in legal else legal[0]
            at_m = router.position(first_pass, first)
            drive.path.append(_Driven(first_pass, at_m, at_m))
            drive.pickups.append(Pickup(first.stop_id, 0, at_m, first_pass != first.required_pass))
            drive.load = 1
        while run:
            if sites is not None and capacity is not None and drive.load >= capacity:
                if not drive.visit(PlaceVisit(sites.disposal, unload=True)):
                    unreachable.extend(s.stop_id for s in run)
                    break
                drive.load = 0
            passed = router.passed_recently(drive.path, run) if drive.at_node is None else None
            leg = router.nearest(drive.seeds(), run)
            if passed is not None and (leg is None or not _better(leg, passed)):
                leg = passed
            if leg is None:
                unreachable.extend(s.stop_id for s in run)
                break
            drive.collect(run.pop(leg.stop_index), leg)

    closing: tuple[PlaceVisit, ...] = ()
    if sites is not None and drive.pickups:
        closing = _finish(drive, sites)

    serviced: dict[int, list[str]] = defaultdict(list)
    for pickup in drive.pickups:
        serviced[pickup.traversal_index].append(pickup.stop_id)
    traversals = tuple(
        Traversal(d.on_pass, d.start_m, d.end_m, tuple(serviced.get(i, ())))
        for i, d in enumerate(drive.path)
    )
    return DrivenRoute(
        traversals,
        tuple(drive.joins),
        tuple(drive.pickups),
        tuple(unreachable),
        allowed_u_turns,
        start=sites.yard if sites is not None else None,
        closing_visits=closing,
        end=sites.yard if sites is not None else None,
    )


def _finish(drive: _Drive, sites: RouteSites) -> tuple[PlaceVisit, ...]:
    """The final unload and the drive back to the yard; returns the visits after the last pass."""
    reached = drive.visit(PlaceVisit(sites.disposal, unload=True))
    assert reached, "the truck only drives passes that can reach the disposal site"
    if sites.disposal.node != sites.yard.node:
        if not drive.visit(PlaceVisit(sites.yard, unload=False)):
            raise ValueError("the yard cannot be reached from the disposal site")
        drive.pending.pop()  # arriving at the yard ends the route; it is not a visit
    closing = tuple(drive.pending)
    drive.pending.clear()
    return closing
