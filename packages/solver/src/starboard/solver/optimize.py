"""The optimized route: every required pass, in the quickest legal order.

Each stop's required pass is the direction of travel that puts its cart on
the truck's right, so a route made of required passes collects every cart
from the right. The required passes are the nodes of a line graph (HANDOFF
§2.3): the cost from one to the next is the quickest legal connection
between them plus driving and servicing the next one. OR-Tools routing
(https://developers.google.com/optimization/routing) orders them, starting
from the current route's order when one is given, with a capacity dimension
whose optional disposal visits unload the truck (the reload pattern of the
OR-Tools `cvrp_reload` sample). The order is then improved by 2-opt and
or-opt moves, and disposal visits are placed optimally for the final order.

The route starts at the yard, collects, visits the disposal site whenever the
next pass would overfill the truck (or whenever going through it is quicker)
and once more at the end, and returns to the yard. Search stops after a
fixed number of solutions, not a wall-clock time, so the same input gives
the same route.
"""

import itertools
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from ortools.constraint_solver import pywrapcp, routing_enums_pb2, routing_parameters_pb2

from starboard.solver import defaults
from starboard.solver.connections import UNREACHABLE, ConnectionCosts, traversal_ms
from starboard.solver.graph import (
    Direction,
    Pass,
    Place,
    SnappedStop,
    StateGraph,
    Transition,
)
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

_MS_PER_S = 1000
# An arc the truck cannot drive costs this; no accepted plan uses one.
_NO_ARC_MS = 10**9


@dataclass(frozen=True, slots=True)
class SolveSettings:
    """How to solve: the truck, the routing rules, and the search size.

    `solution_limit` overrides `defaults.SOLVER_SOLUTION_LIMIT`, for tests.
    """

    profile: TruckProfile = field(default_factory=TruckProfile)
    rules: RoutingRules = field(default_factory=RoutingRules)
    solution_limit: int | None = None


class UnservedReason(StrEnum):
    NO_LEGAL_PASS = "no_legal_pass"
    UNREACHABLE_FROM_YARD = "unreachable_from_yard"
    UNREACHABLE_FROM_DISPOSAL = "unreachable_from_disposal"
    CANNOT_REACH_DISPOSAL = "cannot_reach_disposal"
    OVER_CAPACITY = "over_capacity"


@dataclass(frozen=True, slots=True)
class UnservedStop:
    """A stop the route cannot serve, with the reason; it goes to the review queue."""

    stop_id: str
    reason: UnservedReason


@dataclass(frozen=True, slots=True)
class Plan:
    """The order of required passes, and after which of them the truck unloads.

    The final unload, after the last pass, is always made and is not listed.
    """

    sequence: tuple[Pass, ...]
    unload_after: tuple[int, ...]
    cost_ms: int


@dataclass(frozen=True, slots=True)
class OptimizedRoute:
    """The route, its plan, the stops it cannot serve, and how the search ended.

    `time_limited` is true when the wall-clock ceiling, not the solution limit,
    stopped the search; such a route may differ on a faster or slower machine.
    """

    route: DrivenRoute
    plan: Plan
    unserved: tuple[UnservedStop, ...]
    over_duration_s: float = 0.0
    solutions_searched: int = 0
    time_limited: bool = False


def _position(graph: StateGraph, on_pass: Pass, stop: SnappedStop) -> float:
    length = graph.segments[on_pass.segment_id].length_m
    along = min(max(stop.distance_along_m, 0.0), length)
    return along if on_pass.direction is Direction.FORWARD else length - along


def _known(value: int) -> int:
    return _NO_ARC_MS if value == UNREACHABLE else value


def _pass_key(p: Pass) -> tuple[str, str]:
    return (p.segment_id, p.direction.value)


class _Costs:
    """Plan costs in integer milliseconds over one set of required passes.

    `pair_ms[(a, b)]` is the cheaper of driving straight from `a` to `b` and
    going by way of the disposal site; with no capacity limit that choice is
    the whole decision about mid-route unloads, so it prices moves exactly.
    """

    def __init__(
        self,
        graph: StateGraph,
        connections: ConnectionCosts,
        sites: RouteSites,
        carts: dict[Pass, int],
    ) -> None:
        self.carts = carts
        self.unload_ms = round(defaults.DISPOSAL_UNLOAD_TIME.value * _MS_PER_S)
        cart_ms = round(defaults.CART_SERVICE_TIME.value * _MS_PER_S)
        self.service_ms = {p: traversal_ms(graph, p) + n * cart_ms for p, n in carts.items()}
        yard, disposal = sites.yard, sites.disposal
        self.return_ms = _known(connections.between_places(disposal, yard))
        passes = list(carts)
        self.link_ms = {
            (a, b): _known(connections.between(a, b)) for a in passes for b in passes if a != b
        }
        self.open_ms = {p: _known(connections.from_place(yard, p)) for p in passes}
        self.to_disposal_ms = {p: _known(connections.to_place(p, disposal)) for p in passes}
        self.from_disposal_ms = {p: _known(connections.from_place(disposal, p)) for p in passes}
        self.pair_ms = {
            (a, b): min(link, self.via_disposal(a, b)) for (a, b), link in self.link_ms.items()
        }

    def via_disposal(self, a: Pass, b: Pass) -> int:
        return self.to_disposal_ms[a] + self.unload_ms + self.from_disposal_ms[b]

    def close(self, a: Pass) -> int:
        return self.to_disposal_ms[a] + self.unload_ms + self.return_ms

    def plan_cost(self, sequence: Sequence[Pass], unload_after: Sequence[int]) -> int:
        if not sequence:
            return 0
        unloads = set(unload_after)
        cost = self.open_ms[sequence[0]] + sum(self.service_ms[p] for p in sequence)
        for k in range(len(sequence) - 1):
            a, b = sequence[k], sequence[k + 1]
            cost += self.via_disposal(a, b) if k in unloads else self.link_ms[(a, b)]
        return cost + self.close(sequence[-1])

    def best_unloads(self, sequence: Sequence[Pass], capacity: int | None) -> Plan:
        """The cheapest places to unload for this order, keeping every load within capacity."""
        if not sequence:
            return Plan((), (), 0)
        if capacity is None:
            unloads = [
                k
                for k in range(len(sequence) - 1)
                if self.via_disposal(sequence[k], sequence[k + 1])
                < self.link_ms[(sequence[k], sequence[k + 1])]
            ]
        else:
            unloads = self._split(sequence, capacity)
        return Plan(tuple(sequence), tuple(unloads), self.plan_cost(sequence, unloads))

    def _split(self, sequence: Sequence[Pass], capacity: int) -> list[int]:
        """Unload points by dynamic programming over loads of consecutive passes."""
        n = len(sequence)
        prefix = [0]
        for k in range(n - 1):
            prefix.append(prefix[-1] + self.link_ms[(sequence[k], sequence[k + 1])])
        unbounded = float("inf")
        # cheapest[i]: least cost of everything before a load that starts at sequence[i].
        cheapest: list[float] = [unbounded] * n
        came_from = [-1] * n
        cheapest[0] = 0
        finish, last_start = unbounded, -1
        for i in range(n):
            if cheapest[i] == unbounded:
                continue
            load = 0
            for j in range(i, n):
                load += self.carts[sequence[j]]
                if load > capacity:
                    break
                within = cheapest[i] + prefix[j] - prefix[i]
                if j == n - 1:
                    if within < finish:
                        finish, last_start = within, i
                else:
                    candidate = within + self.via_disposal(sequence[j], sequence[j + 1])
                    if candidate < cheapest[j + 1]:
                        cheapest[j + 1], came_from[j + 1] = candidate, i
        if last_start < 0:
            raise ValueError("a single pass holds more carts than the truck")
        unloads: list[int] = []
        start = last_start
        while start > 0:
            unloads.append(start - 1)
            start = came_from[start]
        return sorted(unloads)


def _required_passes(
    graph: StateGraph, stops: Sequence[SnappedStop]
) -> tuple[dict[Pass, list[SnappedStop]], list[UnservedStop]]:
    legal = set(graph.passes)
    on_pass: dict[Pass, list[SnappedStop]] = defaultdict(list)
    unserved: list[UnservedStop] = []
    for stop in stops:
        if stop.required_pass in legal:
            on_pass[stop.required_pass].append(stop)
        else:
            unserved.append(UnservedStop(stop.stop_id, UnservedReason.NO_LEGAL_PASS))
    for p, served in on_pass.items():
        served.sort(key=lambda s: (_position(graph, p, s), s.stop_id))
    return dict(on_pass), unserved


class _LineGraphModel:
    """The OR-Tools model: the yard, every required pass, optional disposal visits, the end.

    Node 0 is the yard; then the required passes; then the optional disposal
    visits; the last node is the final unload and return to the yard. The
    cost of arriving at a pass includes driving and servicing it, so a
    route's total is its route time.
    """

    def __init__(self, costs: _Costs, passes: list[Pass], disposal_visits: int) -> None:
        self.costs = costs
        self.passes = passes
        self.first_pass = 1
        self.first_visit = 1 + len(passes)
        self.end = self.first_visit + disposal_visits
        self.size = self.end + 1

    def is_visit(self, node: int) -> bool:
        return self.first_visit <= node < self.end

    def pass_at(self, node: int) -> Pass:
        return self.passes[node - self.first_pass]

    def arc(self, i: int, j: int) -> int:
        into_start, out_of_end = j in {i, 0}, i == self.end
        if into_start or out_of_end or (i == 0 and (j == self.end or self.is_visit(j))):
            return _NO_ARC_MS
        costs = self.costs
        if j == self.end:
            return costs.return_ms if self.is_visit(i) else costs.close(self.pass_at(i))
        if self.is_visit(j):
            return _NO_ARC_MS if self.is_visit(i) else self._to_visit(i)
        b = self.pass_at(j)
        if i == 0:
            return costs.open_ms[b] + costs.service_ms[b]
        if self.is_visit(i):
            return costs.from_disposal_ms[b] + costs.service_ms[b]
        return costs.link_ms[(self.pass_at(i), b)] + costs.service_ms[b]

    def _to_visit(self, i: int) -> int:
        return self.costs.to_disposal_ms[self.pass_at(i)] + self.costs.unload_ms

    def matrix(self) -> list[list[int]]:
        return [[self.arc(i, j) for j in range(self.size)] for i in range(self.size)]


def _search_parameters(solution_limit: int) -> routing_parameters_pb2.RoutingSearchParameters:
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.solution_limit = solution_limit
    params.time_limit.FromSeconds(round(defaults.SOLVER_TIME_LIMIT.value))
    # The completion search inside insertion moves is bounded by wall time unless this
    # is raised; at its 0.1 s default a slower machine could give a different route.
    params.lns_time_limit.FromSeconds(round(defaults.SOLVER_TIME_LIMIT.value))
    params.log_search = False
    return params


def _add_load(
    routing: pywrapcp.RoutingModel,
    manager: pywrapcp.RoutingIndexManager,
    model: _LineGraphModel,
    capacity: int,
) -> None:
    """A load dimension: passes add their carts and a disposal visit empties the truck.

    Slack is allowed only at disposal visits, so the load drops to zero there and
    nowhere else, as in the OR-Tools cvrp_reload sample.
    """
    demands = [0] * model.size
    for k, p in enumerate(model.passes):
        demands[model.first_pass + k] = model.costs.carts[p]
    for node in range(model.first_visit, model.end):
        demands[node] = -capacity
    demand = routing.RegisterUnaryTransitVector(demands)
    routing.AddDimensionWithVehicleCapacity(demand, capacity, [capacity], True, "load")
    load = routing.GetDimensionOrDie("load")
    for node in range(model.end):
        if not model.is_visit(node):
            load.SlackVar(manager.NodeToIndex(node)).SetValue(0)


def _warm_nodes(model: _LineGraphModel, plan: Plan) -> list[int]:
    """The warm-start route as model nodes, with a disposal visit after each unload."""
    index_of = {p: model.first_pass + k for k, p in enumerate(model.passes)}
    free_visits = iter(range(model.first_visit, model.end))
    nodes: list[int] = []
    for k, p in enumerate(plan.sequence):
        nodes.append(index_of[p])
        if k in plan.unload_after:
            nodes.append(next(free_visits))
    return nodes


def _solve_order(
    costs: _Costs,
    passes: list[Pass],
    warm_order: list[Pass],
    profile: TruckProfile,
    solution_limit: int,
) -> tuple[list[Pass], int, bool]:
    """An order of `passes` from OR-Tools routing, how many solutions it searched, and
    whether the wall-clock ceiling stopped it (then the route can vary by machine)."""
    capacity = profile.capacity_carts
    warm_plan = costs.best_unloads(warm_order, capacity) if warm_order else None
    needed = 0 if capacity is None else max(0, -(-sum(costs.carts.values()) // capacity) - 1)
    if warm_plan is not None:
        needed = max(needed, len(warm_plan.unload_after))
    model = _LineGraphModel(costs, passes, needed + round(defaults.SPARE_DISPOSAL_VISITS.value))
    matrix = model.matrix()

    manager = pywrapcp.RoutingIndexManager(model.size, 1, [0], [model.end])
    routing = pywrapcp.RoutingModel(manager)
    transit = routing.RegisterTransitMatrix(matrix)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    for node in range(model.first_visit, model.end):
        routing.AddDisjunction([manager.NodeToIndex(node)], 0)
    if capacity is not None:
        _add_load(routing, manager, model, capacity)
    if profile.max_route_duration_s is not None:
        routing.AddDimension(transit, 0, sum(max(row) for row in matrix), True, "time")
        routing.GetDimensionOrDie("time").SetCumulVarSoftUpperBound(
            routing.End(0),
            round(profile.max_route_duration_s * _MS_PER_S),
            round(defaults.DURATION_EXCESS_COST.value),
        )

    params = _search_parameters(solution_limit)
    solution = None
    if warm_plan is not None:
        routing.CloseModelWithParameters(params)
        initial = routing.ReadAssignmentFromRoutes([_warm_nodes(model, warm_plan)], True)
        if initial is not None:
            solution = routing.SolveFromAssignmentWithParameters(initial, params)
    if solution is None:
        solution = routing.SolveWithParameters(params)
    if solution is None:
        return list(warm_order or passes), 0, False

    order: list[Pass] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if model.first_pass <= node < model.first_visit:
            order.append(model.pass_at(node))
        index = solution.Value(routing.NextVar(index))
    timed_out = routing.solver().WallTime() / _MS_PER_S >= defaults.SOLVER_TIME_LIMIT.value
    return order, routing.solver().Solutions(), timed_out


class _Sequence:
    """An order of passes with O(1) prices for 2-opt and or-opt moves on `pair_ms`."""

    def __init__(self, costs: _Costs, sequence: list[Pass]) -> None:
        self.costs = costs
        self.passes = sequence
        self.forward = [0]
        self.backward = [0]
        for a, b in itertools.pairwise(sequence):
            self.forward.append(self.forward[-1] + costs.pair_ms[(a, b)])
            self.backward.append(self.backward[-1] + costs.pair_ms[(b, a)])

    def edge(self, a: Pass | None, b: Pass | None) -> int:
        """Cost of following `a` with `b`; None stands for the yard (start) or the end."""
        if a is None and b is None:
            return 0
        if a is None:
            assert b is not None
            return self.costs.open_ms[b]
        if b is None:
            return self.costs.close(a)
        return self.costs.pair_ms[(a, b)]

    def at(self, k: int) -> Pass | None:
        return self.passes[k] if 0 <= k < len(self.passes) else None

    def two_opt_gain(self, i: int, j: int) -> int:
        """How much reversing passes[i..j] saves."""
        before = self.edge(self.at(i - 1), self.at(i)) + self.edge(self.at(j), self.at(j + 1))
        before += self.forward[j] - self.forward[i]
        after = self.edge(self.at(i - 1), self.at(j)) + self.edge(self.at(i), self.at(j + 1))
        after += self.backward[j] - self.backward[i]
        return before - after

    def or_opt_gain(self, i: int, length: int, gap: int) -> int:
        """How much moving passes[i:i+length] to sit just before passes[gap] saves.

        `gap` indexes the original order and lies outside the block; len(passes) means
        moving it to the end.
        """
        first, last = self.at(i), self.at(i + length - 1)
        prev, after = self.at(i - 1), self.at(i + length)
        left, right = self.at(gap - 1), self.at(gap)
        removed = self.edge(prev, first) + self.edge(last, after) - self.edge(prev, after)
        added = self.edge(left, first) + self.edge(last, right) - self.edge(left, right)
        return removed - added


def _improving_move(costs: _Costs, plan: Plan, capacity: int | None) -> Plan | None:
    """The first 2-opt or or-opt move whose best-unload plan beats `plan`, if any."""
    order = _Sequence(costs, list(plan.sequence))
    n = len(order.passes)
    for i in range(n):
        for j in range(i + 1, n):
            if order.two_opt_gain(i, j) > 0:
                candidate = order.passes[:i] + order.passes[i : j + 1][::-1] + order.passes[j + 1 :]
                trial = costs.best_unloads(candidate, capacity)
                if trial.cost_ms < plan.cost_ms:
                    return trial
        for length in (1, 2, 3):
            if i + length > n:
                break
            for gap in range(n + 1):
                if i <= gap <= i + length or order.or_opt_gain(i, length, gap) <= 0:
                    continue
                block = order.passes[i : i + length]
                rest = order.passes[:i] + order.passes[i + length :]
                at = gap if gap < i else gap - length
                trial = costs.best_unloads(rest[:at] + block + rest[at:], capacity)
                if trial.cost_ms < plan.cost_ms:
                    return trial
    return None


def _improve(costs: _Costs, plan: Plan, capacity: int | None) -> Plan:
    """2-opt (reverse a stretch) and or-opt (move 1 to 3 passes) until no move improves.

    Moves are priced in O(1) on `pair_ms`, which is exact with no capacity limit;
    each improving candidate is then priced with its best unloads and kept only if
    that total is lower.
    """
    for _ in range(round(defaults.LOCAL_SEARCH_MAX_ROUNDS.value)):
        better = _improving_move(costs, plan, capacity)
        if better is None:
            break
        plan = better
    return plan


class _Expansion:
    """Turns a plan into the passes, joins and pickups actually driven."""

    def __init__(
        self,
        graph: StateGraph,
        connections: ConnectionCosts,
        stops_on: dict[Pass, list[SnappedStop]],
    ) -> None:
        self.graph = graph
        self.connections = connections
        self.stops_on = stops_on
        self.traversals: list[Traversal] = []
        self.joins: list[Join] = []
        self.pickups: list[Pickup] = []

    def drive(self, p: Pass, collect: bool) -> None:
        index = len(self.traversals)
        served = self.stops_on.get(p, []) if collect else []
        for stop in served:
            self.pickups.append(Pickup(stop.stop_id, index, _position(self.graph, p, stop), False))
        length = self.graph.segments[p.segment_id].length_m
        self.traversals.append(Traversal(p, 0.0, length, tuple(s.stop_id for s in served)))

    def follow(self, transitions: Sequence[Transition], collect_last: bool) -> None:
        for k, t in enumerate(transitions):
            self.joins.append(t)
            self.drive(t.to_pass, collect_last and k == len(transitions) - 1)

    def leave(self, place: Place, target: Pass) -> None:
        first, transitions = self.connections.path_from_place(place, target)
        if not transitions:
            self.drive(target, True)
            return
        self.drive(first, False)
        self.follow(transitions, True)

    def route(self, sites: RouteSites, plan: Plan, allowed_u_turns: frozenset[int]) -> DrivenRoute:
        yard, disposal = sites.yard, sites.disposal
        sequence = plan.sequence
        if not sequence:
            return DrivenRoute((), (), (), (), allowed_u_turns, start=yard, end=yard)
        self.leave(yard, sequence[0])
        for k in range(len(sequence) - 1):
            a, b = sequence[k], sequence[k + 1]
            if k in plan.unload_after:
                self.follow(self.connections.path_to_place(a, disposal), False)
                self.joins.append(PlaceVisit(disposal, unload=True))
                self.leave(disposal, b)
            else:
                self.follow(self.connections.path_between(a, b), True)
        self.follow(self.connections.path_to_place(sequence[-1], disposal), False)
        closing: tuple[PlaceVisit, ...] = ()
        if disposal.node == yard.node:
            closing = (PlaceVisit(disposal, unload=True),)
        else:
            self.joins.append(PlaceVisit(disposal, unload=True))
            first, transitions = self.connections.path_between_places(disposal, yard)
            if first is not None:
                self.drive(first, False)
                self.follow(transitions, False)
        return DrivenRoute(
            tuple(self.traversals),
            tuple(self.joins),
            tuple(self.pickups),
            (),
            allowed_u_turns,
            start=yard,
            closing_visits=closing,
            end=yard,
        )


def _unservable(
    connections: ConnectionCosts, sites: RouteSites, profile: TruckProfile, p: Pass, carts: int
) -> UnservedReason | None:
    if connections.from_place(sites.yard, p) == UNREACHABLE:
        return UnservedReason.UNREACHABLE_FROM_YARD
    if connections.to_place(p, sites.disposal) == UNREACHABLE:
        return UnservedReason.CANNOT_REACH_DISPOSAL
    if connections.from_place(sites.disposal, p) == UNREACHABLE:
        return UnservedReason.UNREACHABLE_FROM_DISPOSAL
    if profile.capacity_carts is not None and carts > profile.capacity_carts:
        return UnservedReason.OVER_CAPACITY
    return None


def optimize(
    graph: StateGraph,
    stops: Sequence[SnappedStop],
    sites: RouteSites,
    settings: SolveSettings | None = None,
    warm_start: Sequence[SnappedStop] | None = None,
) -> OptimizedRoute:
    """The quickest route that collects every servable stop from the right.

    `warm_start` is the current route's stop order, used as the starting
    solution; `stops` in their given order are used when it is omitted.
    Raises ValueError if the yard cannot be reached from the disposal site.
    """
    settings = settings or SolveSettings()
    profile = settings.profile
    allowed_u_turns = u_turn_nodes(graph, stops, settings.rules)
    stops_on, unserved = _required_passes(graph, stops)
    connections = ConnectionCosts(graph, allowed_u_turns, stops_on, [sites.yard, sites.disposal])
    if connections.between_places(sites.disposal, sites.yard) == UNREACHABLE:
        raise ValueError("the yard cannot be reached from the disposal site")

    # Passes the truck cannot reach, leave, or fit in one load go to review.
    for p in sorted(stops_on, key=_pass_key):
        reason = _unservable(connections, sites, profile, p, len(stops_on[p]))
        if reason is not None:
            unserved.extend(UnservedStop(s.stop_id, reason) for s in stops_on.pop(p))

    passes = sorted(stops_on, key=_pass_key)
    costs = _Costs(graph, connections, sites, {p: len(stops_on[p]) for p in passes})
    warm_order = list(
        dict.fromkeys(
            s.required_pass
            for s in (warm_start if warm_start is not None else stops)
            if s.required_pass in stops_on
        )
    )
    limit = settings.solution_limit or round(defaults.SOLVER_SOLUTION_LIMIT.value)
    order, searched, timed_out = (
        _solve_order(costs, passes, warm_order, profile, limit) if passes else ([], 0, False)
    )
    plan = _improve(
        costs, costs.best_unloads(order, profile.capacity_carts), profile.capacity_carts
    )
    route = _Expansion(graph, connections, stops_on).route(sites, plan, allowed_u_turns)

    over = 0.0
    if profile.max_route_duration_s is not None:
        over = max(0.0, plan.cost_ms / _MS_PER_S - profile.max_route_duration_s)
    return OptimizedRoute(route, plan, tuple(unserved), over, searched, timed_out)
