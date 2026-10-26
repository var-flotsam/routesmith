"""The exchange between districts on a hand-built case: it fixes a lopsided split.

Its properties on random grids (never worse, no district split) are in test_fleet.py.
"""

from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import ConnectionCosts
from starboard.solver.districts import unit_costs
from starboard.solver.exchange import ExchangeProblem, exchange_units
from starboard.solver.graph import Place
from starboard.solver.objectives import RouteObjective, acceptance_key
from starboard.solver.optimize import PlanCosts, improve_plan
from starboard.solver.route import RouteSites
from starboard.solver.units import build_units


def _lopsided():
    """Two districts on a 4x4 grid of two-way streets: one street against all the rest."""
    grid = Grid(size=4, one_way_east=frozenset(), one_way_west=frozenset())
    graph = build_state_graph(grid.segments())
    carts = {p: 4 for p in graph.passes}
    units = build_units(graph, carts)
    sites = RouteSites(Place("yard", 0), Place("disposal", 0))
    connections = ConnectionCosts(graph, frozenset(), list(carts), [sites.yard, sites.disposal])
    lonely = units.units[0].unit_id
    district_of = {u.unit_id: 0 if u.unit_id == lonely else 1 for u in units.units}
    plans = []
    for d in range(2):
        passes = [p for u in units.units if district_of[u.unit_id] == d for p in u.required_passes]
        costs = PlanCosts(graph, connections, sites, {p: carts[p] for p in passes})
        plans.append(improve_plan(costs, costs.best_unloads(passes, None), None))
    problem = ExchangeProblem(
        graph,
        connections,
        sites,
        units,
        carts,
        unit_costs(graph, connections, units, sites).distance,
        RouteObjective.BALANCED_TOTAL,
    )
    return problem, district_of, plans


def test_the_exchange_moves_streets_to_a_district_with_too_little_work():
    problem, district_of, plans = _lopsided()
    before = acceptance_key(problem.objective, [p.cost_ms for p in plans])
    result = exchange_units(problem, district_of, plans)
    after = acceptance_key(problem.objective, [p.cost_ms for p in result.plans])
    assert result.moves > 0
    assert result.changed == {0, 1}
    assert after < before
    moved = [u for u, d in result.district_of.items() if d != district_of[u]]
    assert moved
    # Every pass is still served by exactly one plan.
    served = [p for plan in result.plans for p in plan.sequence]
    assert sorted(served, key=str) == sorted(problem.carts, key=str)


def test_the_exchange_is_deterministic():
    problem, district_of, plans = _lopsided()
    assert exchange_units(problem, district_of, plans) == exchange_units(
        problem, district_of, plans
    )
