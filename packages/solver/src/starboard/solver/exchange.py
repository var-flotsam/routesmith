"""Exchange street units between neighbouring districts, priced on route times (ADR-0003).

After every district is routed, two kinds of move are tried between districts
that share a boundary:

- relocate: a cart unit on the boundary moves to the neighbouring district;
- swap: two boundary units, one on each side, trade districts. Each unit is
  paired only with the `defaults.EXCHANGE_SWAP_CANDIDATES` nearest units on
  the other side (granular neighbourhoods, Toth and Vigo 2003,
  https://doi.org/10.1287/ijoc.15.4.333.24890).

Every move is priced by splicing: the leaving passes are dropped from the
donor's order and each arriving pass goes where it adds least to the
receiver's. The best-priced `defaults.EXCHANGE_TRIALS` moves are then
re-optimised: both changed orders get their best unloads and the single-route
local search. The first move whose re-optimised times lower the objective's
acceptance key is kept, and the search starts again, up to
`defaults.EXCHANGE_MAX_MOVES` moves.

Moves keep the partition's district rules: a district never splits into more
pieces than it has and never loses its last cart unit, and both curbs of a
street stay with one truck. Units with a pass the truck can reach only before
its first unload stay where they are, so every moved stop stays servable.
Tail exchange between routes (2-opt*) is not used: a route's tail cuts across
street units, so it would split streets and districts.

Everything is deterministic: candidates are ordered by price, then district
indices, then unit ids.
"""

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from starboard.solver import defaults
from starboard.solver.connections import UNREACHABLE, ConnectionCosts
from starboard.solver.districts import pieces
from starboard.solver.graph import Pass, StateGraph
from starboard.solver.objectives import RouteObjective, acceptance_key
from starboard.solver.optimize import INFEASIBLE_MS, Plan, PlanCosts, improve_plan
from starboard.solver.route import RouteSites
from starboard.solver.units import UnitGraph


@dataclass(frozen=True, slots=True)
class ExchangeProblem:
    """What the exchange needs to know about an area and how routes are judged.

    `carts` holds every pass of every plan; `distance(a, b)` is the unit
    distance in ms, negative when unreachable.
    """

    graph: StateGraph
    connections: ConnectionCosts
    sites: RouteSites
    units: UnitGraph
    carts: Mapping[Pass, int]
    distance: Callable[[str, str], int]
    objective: RouteObjective
    capacity: int | None = None
    max_route_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Exchange:
    """The districts and plans after the exchange, and the districts it changed."""

    district_of: dict[str, int]
    plans: tuple[Plan, ...]
    changed: frozenset[int]
    moves: int


@dataclass(frozen=True, slots=True, order=True)
class _Candidate:
    estimate: tuple[int, ...]
    a: int
    b: int
    to_b: tuple[str, ...]  # units district a gives district b
    to_a: tuple[str, ...]  # units district b gives district a


def _edge(costs: PlanCosts, a: Pass | None, b: Pass | None) -> int:
    """Following `a` with `b` on `pair_ms`; None is the yard before the start or the end."""
    if a is None:
        return 0 if b is None else costs.open_ms[b]
    if b is None:
        return costs.close(a)
    return costs.pair_ms[(a, b)]


def _estimate(costs: PlanCosts, order: Sequence[Pass]) -> int:
    """Route time on `pair_ms`: exact with no capacity, a ranking estimate with one."""
    if not order:
        return 0
    driven = sum(costs.service_ms[p] for p in order)
    links = sum(costs.pair_ms[(a, b)] for a, b in itertools.pairwise(order))
    return costs.open_ms[order[0]] + driven + links + costs.close(order[-1])


def _splice(
    costs: PlanCosts, order: Sequence[Pass], leaving: set[Pass], arriving: Sequence[Pass]
) -> list[Pass]:
    """`order` without `leaving`, with each arriving pass where it adds least."""
    spliced = [p for p in order if p not in leaving]
    for p in arriving:
        best_at, best_ms = 0, None
        for at in range(len(spliced) + 1):
            prev = spliced[at - 1] if at > 0 else None
            nxt = spliced[at] if at < len(spliced) else None
            added = _edge(costs, prev, p) + _edge(costs, p, nxt) - _edge(costs, prev, nxt)
            if best_ms is None or added < best_ms:
                best_at, best_ms = at, added
        spliced.insert(best_at, p)
    return spliced


@dataclass(slots=True)
class _State:
    problem: ExchangeProblem
    district_of: dict[str, int]
    plans: list[Plan]
    _costs: dict[tuple[int, int], PlanCosts] = field(default_factory=dict)

    @property
    def times(self) -> list[int]:
        return [p.cost_ms for p in self.plans]

    def key(self, times: Sequence[int]) -> tuple[int, ...]:
        return acceptance_key(self.problem.objective, times, self.problem.max_route_ms)

    def members(self, district: int) -> set[str]:
        return {u for u, d in self.district_of.items() if d == district}

    def costs(self, a: int, b: int) -> PlanCosts:
        """Plan costs over the passes of districts a and b, which a move between them keeps."""
        a, b = min(a, b), max(a, b)
        if (a, b) not in self._costs:
            passes = (*self.plans[a].sequence, *self.plans[b].sequence)
            carts = {p: self.problem.carts[p] for p in passes}
            problem = self.problem
            self._costs[(a, b)] = PlanCosts(
                problem.graph, problem.connections, problem.sites, carts
            )
        return self._costs[(a, b)]

    def movable(self, unit_id: str) -> bool:
        """A cart unit its route serves, with no pass reachable only before the first unload."""
        problem = self.problem
        unit = problem.units.by_id[unit_id]
        if unit.is_connector:
            return False
        served = set(self.plans[self.district_of[unit_id]].sequence)
        disposal = problem.sites.disposal
        return all(
            p in served and problem.connections.from_place(disposal, p) != UNREACHABLE
            for p in unit.required_passes
        )

    def keeps_districts(self, a: int, b: int, to_b: Sequence[str], to_a: Sequence[str]) -> bool:
        units = self.problem.units
        before_a, before_b = self.members(a), self.members(b)
        after_a = (before_a - set(to_b)) | set(to_a)
        after_b = (before_b - set(to_a)) | set(to_b)
        for before, after in ((before_a, after_a), (before_b, after_b)):
            if not any(not units.by_id[u].is_connector for u in after):
                return False
            if pieces(units, after) > pieces(units, before):
                return False
        return True

    def boundary(self, a: int, b: int) -> list[str]:
        """Movable units of district a that touch district b."""
        neighbours = self.problem.units.neighbours
        return [
            u
            for u in sorted(self.members(a))
            if any(self.district_of[n] == b for n in neighbours[u]) and self.movable(u)
        ]

    def orders(self, c: _Candidate) -> tuple[list[Pass], list[Pass]]:
        by_id = self.problem.units.by_id
        costs = self.costs(c.a, c.b)
        leaving_a = [p for u in c.to_b for p in by_id[u].required_passes]
        leaving_b = [p for u in c.to_a for p in by_id[u].required_passes]
        order_a = _splice(costs, self.plans[c.a].sequence, set(leaving_a), leaving_b)
        order_b = _splice(costs, self.plans[c.b].sequence, set(leaving_b), leaving_a)
        return order_a, order_b

    def candidate(self, a: int, b: int, to_b: tuple[str, ...], to_a: tuple[str, ...]) -> _Candidate:
        costs = self.costs(a, b)
        draft = _Candidate((), a, b, to_b, to_a)
        order_a, order_b = self.orders(draft)
        times = self.times
        for k, order in ((a, order_a), (b, order_b)):
            times[k] += _estimate(costs, order) - _estimate(costs, self.plans[k].sequence)
        return _Candidate(self.key(times), a, b, to_b, to_a)

    def candidates(self) -> list[_Candidate]:
        trucks = len(self.plans)
        nearest = round(defaults.EXCHANGE_SWAP_CANDIDATES.value)
        found: list[_Candidate] = []
        for a in range(trucks):
            for b in range(trucks):
                if a == b:
                    continue
                facing_b = self.boundary(a, b)
                if not facing_b:
                    continue
                facing_a = self.boundary(b, a)
                for u in facing_b:
                    if self.keeps_districts(a, b, (u,), ()):
                        found.append(self.candidate(a, b, (u,), ()))
                    if a > b:
                        continue  # each swap once, from the lower district
                    closest = sorted(facing_a, key=lambda v: (self._distance(u, v), v))
                    for v in closest[:nearest]:
                        if self.keeps_districts(a, b, (u,), (v,)):
                            found.append(self.candidate(a, b, (u,), (v,)))
        return sorted(found)

    def _distance(self, u: str, v: str) -> int:
        value = self.problem.distance(u, v)
        return INFEASIBLE_MS if value < 0 else value

    def reoptimise(self, c: _Candidate) -> tuple[Plan, Plan] | None:
        costs = self.costs(c.a, c.b)
        capacity = self.problem.capacity
        plans = []
        for order in self.orders(c):
            if not order:
                return None  # every route keeps at least one pass to serve
            plan = costs.best_unloads(order, capacity)
            if plan.cost_ms >= INFEASIBLE_MS:
                return None
            plans.append(improve_plan(costs, plan, capacity))
        return plans[0], plans[1]

    def apply(self, c: _Candidate, plan_a: Plan, plan_b: Plan) -> None:
        for u in c.to_b:
            self.district_of[u] = c.b
        for u in c.to_a:
            self.district_of[u] = c.a
        self.plans[c.a], self.plans[c.b] = plan_a, plan_b
        pair = (min(c.a, c.b), max(c.a, c.b))
        self._costs = {k: v for k, v in self._costs.items() if k == pair or not set(k) & set(pair)}


def exchange_units(
    problem: ExchangeProblem, district_of: Mapping[str, int], plans: Sequence[Plan]
) -> Exchange:
    """Move and swap boundary units while that lowers the acceptance key.

    `plans[k]` is district k's route plan; every pass of it must be in
    `problem.carts`, and every unit's required passes in the plan of its district
    unless the district's route left them unserved.
    """
    state = _State(problem, dict(district_of), list(plans))
    trials = round(defaults.EXCHANGE_TRIALS.value)
    changed: set[int] = set()
    moves = 0
    for _ in range(round(defaults.EXCHANGE_MAX_MOVES.value)):
        current = state.key(state.times)
        kept = False
        for c in state.candidates()[:trials]:
            reoptimised = state.reoptimise(c)
            if reoptimised is None:
                continue
            times = state.times
            times[c.a], times[c.b] = reoptimised[0].cost_ms, reoptimised[1].cost_ms
            if state.key(times) < current:
                state.apply(c, *reoptimised)
                changed |= {c.a, c.b}
                moves += 1
                kept = True
                break
        if not kept:
            break
    return Exchange(state.district_of, tuple(state.plans), frozenset(changed), moves)
