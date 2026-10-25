import itertools

import pytest
from hypothesis import assume, given
from hypothesis import settings as settings_
from hypothesis import strategies as st

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import ConnectionCosts
from starboard.solver.graph import Place, SnappedStop, StreetSegment
from starboard.solver.optimize import (  # the private names are tested against brute force
    INFEASIBLE_MS,
    PlanCosts,
    RouteSites,
    SolveSettings,
    TruckProfile,
    UnservedReason,
    _required_passes,
    _Sequence,
    improve_plan,
    optimize,
)
from starboard.solver.route import PlaceVisit
from starboard.solver.rules import RoutingRules, u_turn_nodes
from starboard.solver.scorecard import score

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())
SNAPPER = Snapper(GRAPH)
SITES = RouteSites(Place("yard", GRID.node(0, 0)), Place("disposal", GRID.node(3, 3)))
SMALL = 60


def stop(stop_id: str, x: float, y: float, graph=GRAPH) -> SnappedStop:
    snapper = SNAPPER if graph is GRAPH else Snapper(graph)
    result = snapper.snap(StopPoint(stop_id, GRID.at(x, y)))
    assert isinstance(result, SnappedStop), result
    return result


def settings(**profile) -> SolveSettings:
    return SolveSettings(TruckProfile(**profile), solution_limit=SMALL)


def test_one_stop_is_collected_from_the_right_between_yard_and_disposal():
    result = optimize(GRAPH, [stop("a", 150, -10)], SITES, settings())
    route = result.route
    assert [p.stop_id for p in route.pickups] == ["a"]
    assert not route.pickups[0].wrong_side
    assert route.start == route.end == SITES.yard
    assert [v.place for v in route.place_visits] == [SITES.disposal]
    assert result.unserved == ()


def test_a_full_truck_unloads_before_collecting_more():
    xs = (30, 70, 130, 170)  # away from the intersections
    stops = [stop(f"s{k}", x, -10) for k, x in enumerate(xs)]  # row 0, south curb
    stops += [stop(f"t{k}", x, 290) for k, x in enumerate(xs)]  # row 3, south curb
    result = optimize(GRAPH, stops, SITES, settings(capacity_carts=4))
    route = result.route
    assert len(route.pickups) == 8
    # Replay the load: it never passes 4, and the truck unloads as soon as it is full.
    collected = [0] * len(route.traversals)
    for pickup in route.pickups:
        collected[pickup.traversal_index] += 1
    load = 0
    for index, carts in enumerate(collected):
        load += carts
        assert load <= 4
        join = route.joins[index] if index < len(route.joins) else None
        if isinstance(join, PlaceVisit) and join.unload:
            load = 0
    assert score(GRAPH, route).disposal_visits == len(result.plan.unload_after) + 1 == 2


def test_a_pass_holding_more_carts_than_the_truck_goes_to_review():
    stops = [stop(f"s{k}", 30 + 15 * k, -10) for k in range(3)]  # one pass, three carts
    result = optimize(GRAPH, stops, SITES, settings(capacity_carts=2))
    assert {u.reason for u in result.unserved} == {UnservedReason.OVER_CAPACITY}
    assert result.route.pickups == ()


def test_time_over_the_maximum_route_duration_is_reported():
    stops = [stop("a", 150, -10), stop("b", 250, 290)]
    result = optimize(GRAPH, stops, SITES, settings(max_route_duration_s=10.0))
    assert result.over_duration_s > 0
    assert len(result.route.pickups) == 2


def test_a_disposal_site_with_no_way_back_to_the_yard_is_refused():
    trap = StreetSegment(
        segment_id="trap",
        from_node=GRID.node(0, 0),
        to_node=999,
        geometry=(GRID.at(0, 0), GRID.at(0, -100)),
        length_m=100.0,
        name="One Way In",
        forward_allowed=True,
        reverse_allowed=False,
        road_class="residential",
    )
    graph = build_state_graph([*GRID.segments(), trap])
    sites = RouteSites(Place("yard", GRID.node(3, 3)), Place("disposal", 999))
    with pytest.raises(ValueError, match="yard cannot be reached"):
        optimize(graph, [stop("a", 150, -10, graph)], sites, settings())


def test_the_warm_start_does_not_change_which_stops_are_served():
    stops = [stop("a", 150, -10), stop("b", 250, 290), stop("c", 110, 150)]
    cold = optimize(GRAPH, stops, SITES, settings())
    warm = optimize(GRAPH, stops, SITES, settings(), warm_start=list(reversed(stops)))
    assert {p.stop_id for p in cold.route.pickups} == {p.stop_id for p in warm.route.pickups}
    assert warm.plan.cost_ms <= warm.start_cost_ms


# The unload placement and the move prices, against brute force on small orders.


def _costs_for(stops, capacity):
    """The optimizer's own cost tables for these stops' required passes."""
    stops_on, _ = _required_passes(GRAPH, stops)
    allowed = u_turn_nodes(GRAPH, stops, RoutingRules())  # the rules optimize() uses
    connections = ConnectionCosts(GRAPH, allowed, stops_on, [SITES.yard, SITES.disposal])
    return PlanCosts(GRAPH, connections, SITES, {p: len(v) for p, v in stops_on.items()})


PLACES = [(x, y) for x in (30, 70, 130, 170, 230, 270) for y in (-10, 90, 290)]


@given(
    st.lists(st.sampled_from(PLACES), min_size=1, max_size=7, unique=True),
    st.none() | st.integers(1, 4),
    st.randoms(use_true_random=False),
)
@settings_(deadline=None)
def test_unloads_are_placed_optimally_for_an_order(places, capacity, rnd):
    stops = [stop(f"s{k}", x, y) for k, (x, y) in enumerate(places)]
    costs = _costs_for(stops, capacity)
    assume(capacity is None or max(costs.carts.values()) <= capacity)  # else it goes to review
    order = sorted(costs.carts, key=lambda p: (p.segment_id, p.direction.value))
    rnd.shuffle(order)
    plan = costs.best_unloads(order, capacity)
    best = None
    for mask in range(1 << max(len(order) - 1, 0)):
        unloads = [k for k in range(len(order) - 1) if mask >> k & 1]
        bounds = [-1, *unloads, len(order) - 1]
        loads = [
            sum(costs.carts[p] for p in order[a + 1 : b + 1]) for a, b in itertools.pairwise(bounds)
        ]
        if capacity is not None and max(loads) > capacity:
            continue
        cost = costs.plan_cost(order, unloads)
        best = cost if best is None else min(best, cost)
    assert best is not None
    assert plan.cost_ms == best


@given(
    st.lists(st.sampled_from(PLACES), min_size=3, max_size=8, unique=True),
    st.data(),
)
@settings_(deadline=None)
def test_move_prices_match_the_recomputed_cost(places, data):
    stops = [stop(f"s{k}", x, y) for k, (x, y) in enumerate(places)]
    costs = _costs_for(stops, None)
    order = sorted(costs.carts, key=lambda p: (p.segment_id, p.direction.value))
    n = len(order)
    if n < 3:
        return
    seq = _Sequence(costs, order)

    def total(sequence):
        return sum(seq.edge(a, b) for a, b in itertools.pairwise([None, *sequence, None]))

    i = data.draw(st.integers(0, n - 2))
    j = data.draw(st.integers(i + 1, n - 1))
    reversed_order = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
    assert seq.two_opt_gain(i, j) == total(order) - total(reversed_order)

    length = data.draw(st.integers(1, min(3, n - 1)))
    i = data.draw(st.integers(0, n - length))
    gap = data.draw(st.sampled_from([g for g in range(n + 1) if not i <= g <= i + length]))
    block, rest = order[i : i + length], order[:i] + order[i + length :]
    at = gap if gap < i else gap - length
    moved = rest[:at] + block + rest[at:]
    assert seq.or_opt_gain(i, length, gap) == total(order) - total(moved)


@given(
    st.lists(st.sampled_from(PLACES), min_size=1, max_size=6, unique=True),
    st.none() | st.integers(2, 4),
)
@settings_(deadline=None)
def test_small_routes_are_solved_to_the_brute_force_optimum(places, capacity):
    stops = [stop(f"s{k}", x, y) for k, (x, y) in enumerate(places)]
    costs = _costs_for(stops, capacity)
    assume(capacity is None or max(costs.carts.values()) <= capacity)
    assume(len(costs.carts) <= 5)  # 120 orders at most
    best = min(
        costs.best_unloads(list(order), capacity).cost_ms
        for order in itertools.permutations(costs.carts)
    )
    # The default search size: the small one other tests use is not meant to find optima.
    result = optimize(GRAPH, stops, SITES, SolveSettings(TruckProfile(capacity_carts=capacity)))
    assert result.plan.cost_ms == best


@given(
    st.lists(st.sampled_from(PLACES), min_size=3, max_size=8, unique=True),
    st.none() | st.integers(2, 4),
    st.randoms(use_true_random=False),
)
@settings_(deadline=None)
def test_local_search_ends_where_no_2_opt_or_or_opt_move_helps(places, capacity, rnd):
    """Short orders price every move exactly, so the search ends at a local optimum."""
    stops = [stop(f"s{k}", x, y) for k, (x, y) in enumerate(places)]
    costs = _costs_for(stops, capacity)
    assume(capacity is None or max(costs.carts.values()) <= capacity)
    order = sorted(costs.carts, key=lambda p: (p.segment_id, p.direction.value))
    rnd.shuffle(order)
    start = costs.best_unloads(order, capacity)
    assume(start.cost_ms < INFEASIBLE_MS)
    improved = improve_plan(costs, start, capacity)
    assert improved.cost_ms <= start.cost_ms
    sequence = list(improved.sequence)
    n = len(sequence)
    neighbours = [
        sequence[:i] + sequence[i : j + 1][::-1] + sequence[j + 1 :]
        for i in range(n)
        for j in range(i + 1, n)
    ]
    for i in range(n):
        for length in (1, 2, 3):
            block, rest = sequence[i : i + length], sequence[:i] + sequence[i + length :]
            neighbours += [rest[:at] + block + rest[at:] for at in range(len(rest) + 1)]
    assert all(
        costs.best_unloads(other, capacity).cost_ms >= improved.cost_ms for other in neighbours
    )
