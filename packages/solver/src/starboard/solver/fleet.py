"""Several routes in one area: districts first, then the single-route solver (ADR-0003).

`solve_routes` splits the area's street units into one district per truck,
routes each district with `optimize` on the whole network, exchanges street
units between neighbouring districts while that lowers the objective
(`exchange.py`), solves the changed districts again, keeps the better of the
two route sets by acceptance key, and checks the
result with `check_route_set`, which re-derives every hard constraint from
the routes themselves: invariants 1 to 4 for each route, and invariant 5
for the set (exactly N routes, each serving at least one stop, every
servable stop served by exactly one route, all from the shared yard and
disposal site). A failed check is a solver defect: it raises, and no route
set is returned.

District solves run through a `map` function the caller passes in (the
built-in `map` by default; a worker can pass a process pool's), so the
solver itself starts no processes. Results are gathered by district index.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from starboard.solver import defaults
from starboard.solver.connections import ConnectionCosts
from starboard.solver.districts import partition, unit_costs
from starboard.solver.exchange import ExchangeProblem, exchange_units
from starboard.solver.graph import Direction, Pass, SnappedStop, StateGraph, Transition
from starboard.solver.objectives import (
    RouteObjective,
    acceptance_key,
    balance_excess_ms,
    check_objective,
    gap,
    lower_bounds_ms,
)
from starboard.solver.optimize import (
    OptimizedRoute,
    Plan,
    SolveSettings,
    UnservedStop,
    optimize,
    unservable_reason,
)
from starboard.solver.route import DrivenRoute, PlaceVisit, RouteSites
from starboard.solver.rules import u_turn_nodes
from starboard.solver.units import build_units

_MS_PER_S = 1000


class RouteSetError(AssertionError):
    """A returned route set breaks a hard constraint: a solver defect, not a data error."""


@dataclass(frozen=True, slots=True)
class RouteSet:
    """One optimized route per truck, and how good the set is.

    `routes[k]` serves district k. `key` is the objective's acceptance key;
    `total_bound_ms` and `longest_bound_ms` are lower bounds, and `gap` how far
    the total may be from best. `balance_met` is whether every route is within
    the balance margin of the average.
    """

    routes: tuple[OptimizedRoute, ...]
    district_of: dict[str, int]
    objective: RouteObjective
    key: tuple[int, ...]
    total_ms: int
    longest_ms: int
    total_bound_ms: int
    longest_bound_ms: int
    gap: float
    balance_met: bool
    unserved: tuple[UnservedStop, ...]


@dataclass(frozen=True, slots=True)
class _DistrictJob:
    graph: StateGraph
    stops: tuple[SnappedStop, ...]
    sites: RouteSites
    settings: SolveSettings
    warm_start: tuple[SnappedStop, ...]


def _solve_district(job: _DistrictJob) -> OptimizedRoute:
    return optimize(job.graph, job.stops, job.sites, job.settings, warm_start=job.warm_start)


@dataclass(frozen=True, slots=True)
class Area:
    """The network, the area's snapped stops, and the shared yard and disposal site."""

    graph: StateGraph
    stops: tuple[SnappedStop, ...]
    sites: RouteSites


@dataclass(frozen=True, slots=True)
class FleetSettings:
    """How many trucks, what best means, and how each route is solved.

    `map_function` runs the district solves; pass a process pool's `map` to run them
    in parallel. It must return results in the order of its inputs. `exchange`
    turns on the exchange of street units between districts after the first solve.
    """

    trucks: int
    objective: RouteObjective = RouteObjective.BALANCED_TOTAL
    solve: SolveSettings = field(default_factory=SolveSettings)
    map_function: Callable[..., Iterable[OptimizedRoute]] = map
    exchange: bool = True


def trucks_for(stops: int) -> int:
    """The fewest trucks that keep every route within `defaults.MAX_STOPS_PER_ROUTE` stops."""
    return max(1, math.ceil(stops / defaults.MAX_STOPS_PER_ROUTE.value))


def solve_routes(
    area: Area, fleet: FleetSettings, warm_start: Sequence[SnappedStop] | None = None
) -> RouteSet:
    """Split the area into `fleet.trucks` routes and solve each; ValueError on bad input."""
    graph, stops, sites, trucks = area.graph, area.stops, area.sites, fleet.trucks
    objective, map_function = fleet.objective, fleet.map_function
    settings = fleet.solve
    check_objective(objective, settings.profile.max_route_duration_s)
    allowed = u_turn_nodes(graph, stops, settings.rules)
    area_settings = replace(settings, u_turns_at=allowed)
    legal = set(graph.passes)
    every = Counter(s.required_pass for s in stops if s.required_pass in legal)
    connections = ConnectionCosts(graph, allowed, every, [sites.yard, sites.disposal])
    # Passes no truck can serve go to review now, so every district gets work it can do.
    reasons = {
        p: reason
        for p, n in every.items()
        if (reason := unservable_reason(connections, sites, settings.profile, p, n)) is not None
    }
    early = [
        UnservedStop(s.stop_id, reasons[s.required_pass])
        for s in stops
        if s.required_pass in reasons
    ]
    workable = [s for s in stops if s.required_pass not in reasons]
    carts = Counter({p: n for p, n in every.items() if p not in reasons})
    units = build_units(graph, carts)
    costs_of_units = unit_costs(graph, connections, units, sites)
    if trucks == 1:
        district_of = {u.unit_id: 0 for u in units.units}
    else:
        district_of = dict(partition(units, trucks, costs_of_units).district_of)

    unit_of_segment = {sid: u.unit_id for u in units.units for sid in u.segment_ids}

    def stops_of(assignment: Mapping[str, int]) -> dict[int, list[SnappedStop]]:
        by_district: dict[int, list[SnappedStop]] = defaultdict(list)
        for stop in workable:
            unit = unit_of_segment.get(stop.segment_id)
            by_district[assignment[unit] if unit is not None else 0].append(stop)
        return by_district

    def job(stops: list[SnappedStop], order: Sequence[SnappedStop]) -> _DistrictJob:
        own = {s.stop_id for s in stops}
        warm = tuple(s for s in order if s.stop_id in own)
        return _DistrictJob(graph, tuple(stops), sites, area_settings, warm)

    order = list(warm_start if warm_start is not None else workable)
    by_district = stops_of(district_of)
    jobs = [job(by_district[d], order) for d in range(trucks)]
    routes = tuple(map_function(_solve_district, jobs))
    max_s = settings.profile.max_route_duration_s
    max_ms = None if max_s is None else round(max_s * _MS_PER_S)
    bounds = _Bounds(graph, connections, sites, carts, trucks, objective, max_ms)
    result = bounds.route_set(routes, district_of, early)

    if trucks > 1 and fleet.exchange:
        problem = ExchangeProblem(
            graph,
            connections,
            sites,
            units,
            carts,
            costs_of_units.distance,
            objective,
            settings.profile.capacity_carts,
            max_ms,
        )
        swapped = exchange_units(problem, district_of, [r.plan for r in routes])
        if swapped.changed:
            # The changed districts are solved again, from their exchanged orders.
            by_district = stops_of(swapped.district_of)
            changed = sorted(swapped.changed)
            again = [job(by_district[d], _in_plan_order(swapped.plans[d], order)) for d in changed]
            resolved = list(routes)
            for d, route in zip(changed, map_function(_solve_district, again), strict=True):
                resolved[d] = route
            exchanged = bounds.route_set(tuple(resolved), swapped.district_of, early)
            if exchanged.key < result.key:
                result = exchanged
    check_route_set(area, settings, result, allowed)
    return result


def _in_plan_order(plan: Plan, stops: Sequence[SnappedStop]) -> list[SnappedStop]:
    """The stops in the order the plan serves their passes; others keep their order, last."""
    rank = {p: k for k, p in enumerate(plan.sequence)}
    return sorted(stops, key=lambda s: rank.get(s.required_pass, len(rank)))


@dataclass(frozen=True, slots=True)
class _Bounds:
    """How good a set of routes is: the acceptance key, the lower bounds and the gap."""

    graph: StateGraph
    connections: ConnectionCosts
    sites: RouteSites
    carts: Mapping[Pass, int]
    trucks: int
    objective: RouteObjective
    max_route_ms: int | None

    def route_set(
        self,
        routes: tuple[OptimizedRoute, ...],
        district_of: dict[str, int],
        early: Sequence[UnservedStop],
    ) -> RouteSet:
        times = [r.plan.cost_ms for r in routes]
        carts = self.carts
        served = {p: n for p, n in carts.items() if any(p in r.plan.sequence for r in routes)}
        total_bound, longest_bound = lower_bounds_ms(
            self.graph, self.connections, self.sites, served, self.trucks
        )
        return RouteSet(
            routes=routes,
            district_of=district_of,
            objective=self.objective,
            key=acceptance_key(self.objective, times, self.max_route_ms),
            total_ms=sum(times),
            longest_ms=max(times, default=0),
            total_bound_ms=total_bound,
            longest_bound_ms=longest_bound,
            gap=gap(sum(times), total_bound),
            balance_met=balance_excess_ms(times) == 0,
            unserved=(*early, *(u for r in routes for u in r.unserved)),
        )


def _ends(graph: StateGraph, p: Pass) -> tuple[int, int]:
    s = graph.segments[p.segment_id]
    return (
        (s.from_node, s.to_node) if p.direction is Direction.FORWARD else (s.to_node, s.from_node)
    )


@dataclass(frozen=True, slots=True)
class _RouteChecker:
    """Invariants 1 to 4 for one route, worked out from the route and the network alone."""

    graph: StateGraph
    sites: RouteSites
    capacity: int | None
    allowed_u_turns: frozenset[int]
    required: dict[str, Pass]

    def check(self, route: DrivenRoute) -> None:
        if len(route.joins) != max(len(route.traversals) - 1, 0):
            raise RouteSetError("joins do not link the traversals")
        legal = set(self.graph.passes)
        for t in route.traversals:
            if t.on_pass not in legal:
                raise RouteSetError(f"travel against a one-way on {t.on_pass.segment_id}")
        for k, join in enumerate(route.joins):
            self._check_join(join, route.traversals[k].on_pass, route.traversals[k + 1].on_pass)
        for pickup in route.pickups:
            on = route.traversals[pickup.traversal_index].on_pass
            if pickup.wrong_side or on != self.required[pickup.stop_id]:
                raise RouteSetError(f"stop {pickup.stop_id} is not collected from the right")
        if route.pickups:
            self._check_yard_to_yard(route)
            self._check_loads(route)

    def _check_join(self, join: object, before: Pass, after: Pass) -> None:
        if isinstance(join, PlaceVisit):
            node = join.place.node
            if _ends(self.graph, before)[1] != node or _ends(self.graph, after)[0] != node:
                raise RouteSetError(f"a visit to {join.place.name} is not at its node")
            return
        if not isinstance(join, Transition) or join not in set(self.graph.transitions):
            raise RouteSetError("a join is not a turn in the network")
        if join.forbidden_by_restriction:
            raise RouteSetError(f"a restricted turn at node {join.via_node}")
        if join.is_u_turn and join.via_node not in self.allowed_u_turns:
            raise RouteSetError(f"a U-turn the rules forbid at node {join.via_node}")
        if (join.from_pass, join.to_pass) != (before, after):
            raise RouteSetError("a turn does not join its two passes")

    def _check_yard_to_yard(self, route: DrivenRoute) -> None:
        yard, disposal = self.sites.yard, self.sites.disposal
        if route.start != yard or route.end != yard:
            raise RouteSetError("the route does not start and end at the yard")
        if _ends(self.graph, route.traversals[0].on_pass)[0] != yard.node:
            raise RouteSetError("the first pass does not leave the yard")
        end_node = disposal.node if route.closing_visits else yard.node
        if _ends(self.graph, route.traversals[-1].on_pass)[1] != end_node:
            raise RouteSetError("the last pass does not reach the yard")

    def _check_loads(self, route: DrivenRoute) -> None:
        unloads = [k for k, j in enumerate(route.joins) if isinstance(j, PlaceVisit) and j.unload]
        unloads += [len(route.traversals) - 1] * sum(v.unload for v in route.closing_visits)
        if not unloads or max(p.traversal_index for p in route.pickups) > max(unloads):
            raise RouteSetError("the route does not unload after its last pickup")
        collected = Counter(p.traversal_index for p in route.pickups)
        load, pending = 0, sorted(unloads)
        for k in range(len(route.traversals)):
            load += collected[k]
            if self.capacity is not None and load > self.capacity:
                raise RouteSetError("the truck is loaded beyond its capacity")
            while pending and pending[0] == k:
                load = 0
                pending.pop(0)


def check_route_set(
    area: Area, settings: SolveSettings, result: RouteSet, allowed_u_turns: frozenset[int]
) -> None:
    """Raise RouteSetError if the routes break any hard constraint (invariants 1 to 5)."""
    graph, stops, sites = area.graph, area.stops, area.sites
    required = {s.stop_id: s.required_pass for s in stops}
    checker = _RouteChecker(
        graph, sites, settings.profile.capacity_carts, allowed_u_turns, required
    )
    for route in result.routes:
        checker.check(route.route)
    picked = Counter(p.stop_id for r in result.routes for p in r.route.pickups)
    unserved = {u.stop_id for u in result.unserved}
    if any(n > 1 for n in picked.values()):
        raise RouteSetError("a stop is served by more than one route")
    if set(picked) & unserved or set(picked) | unserved != set(required):
        raise RouteSetError("the routes and the unserved stops do not cover every stop once")
    if any(not r.route.pickups for r in result.routes) and picked:
        raise RouteSetError("a route serves no stop")
