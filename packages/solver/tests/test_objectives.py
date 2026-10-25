import math

import pytest
from hypothesis import given
from hypothesis import settings as settings_
from hypothesis import strategies as st

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import ConnectionCosts
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.objectives import (
    RouteObjective,
    acceptance_key,
    balance_excess_ms,
    check_objective,
    gap,
    lower_bounds_ms,
)
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import RouteSites
from starboard.solver.rules import RoutingRules, u_turn_nodes

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())
SITES = RouteSites(Place("yard", GRID.node(0, 0)), Place("disposal", GRID.node(3, 3)))
PLACES = [(x, y) for x in (30, 70, 130, 170, 230, 270) for y in (-10, 90, 290)]


def test_balanced_total_prefers_balance_then_the_total():
    balanced = [100, 105, 95]
    lopsided = [60, 60, 170]  # less in total, far outside 10% of the average
    key = lambda times: acceptance_key(RouteObjective.BALANCED_TOTAL, times)  # noqa: E731
    assert key(balanced) < key(lopsided)
    assert key([100, 100, 100]) < key([101, 100, 100])


def test_longest_route_prefers_the_shorter_longest_route():
    key = lambda times: acceptance_key(RouteObjective.LONGEST_ROUTE, times)  # noqa: E731
    assert key([150, 150]) < key([100, 160])
    assert key([150, 140]) < key([150, 150])  # same longest: less total wins


def test_time_over_the_maximum_comes_first_under_every_objective():
    for objective in RouteObjective:
        within = acceptance_key(objective, [300, 300], max_route_ms=320)
        over = acceptance_key(objective, [200, 330], max_route_ms=320)
        assert within < over, objective


def test_the_total_objective_needs_a_maximum_duration():
    with pytest.raises(ValueError, match="maximum route duration"):
        check_objective(RouteObjective.TOTAL, None)
    check_objective(RouteObjective.TOTAL, 8 * 3600.0)
    check_objective(RouteObjective.BALANCED_TOTAL, None)


def test_balance_excess_counts_only_time_outside_the_margin():
    assert balance_excess_ms([100, 100]) == 0
    assert balance_excess_ms([95, 105], margin=0.10) == 0
    assert balance_excess_ms([50, 150], margin=0.10) == 80  # each 50 off, 10 allowed


def test_gap_is_zero_at_the_bound():
    assert gap(100, 100) == 0.0
    assert gap(110, 100) == pytest.approx(0.1)


@given(st.lists(st.sampled_from(PLACES), min_size=1, max_size=8, unique=True))
@settings_(deadline=None)
def test_the_lower_bound_never_exceeds_a_found_single_route(places):
    snapper = Snapper(GRAPH)
    stops = [
        s
        for k, (x, y) in enumerate(places)
        if isinstance(s := snapper.snap(StopPoint(f"s{k}", GRID.at(x, y))), SnappedStop)
    ]
    result = optimize(GRAPH, stops, SITES, SolveSettings(solution_limit=40))
    carts: dict = {}
    for s in stops:
        carts[s.required_pass] = carts.get(s.required_pass, 0) + 1
    allowed = u_turn_nodes(GRAPH, stops, RoutingRules())
    connections = ConnectionCosts(GRAPH, allowed, carts, [SITES.yard, SITES.disposal])
    total, longest = lower_bounds_ms(GRAPH, connections, SITES, carts, trucks=1)
    assert total <= result.plan.cost_ms
    assert longest <= result.plan.cost_ms
    assert math.isfinite(gap(result.plan.cost_ms, total))
