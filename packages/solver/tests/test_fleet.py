"""Several routes in one area: invariant 5 and the checker, on random grids."""

import math
from collections import Counter, defaultdict
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import settings as settings_
from hypothesis import strategies as st

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.districts import pieces
from starboard.solver.fleet import Area, FleetSettings, RouteSetError, check_route_set, solve_routes
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import Pickup, RouteSites, TruckProfile
from starboard.solver.rules import u_turn_nodes
from starboard.solver.units import build_units

SMALL = 30  # a small search keeps each example quick; the invariants hold at any size


@st.composite
def areas(draw):
    size = draw(st.integers(4, 6))
    grid = Grid(size=size, one_way_east=frozenset({1}), one_way_west=frozenset())
    graph = build_state_graph(grid.segments())
    snapper = Snapper(graph)
    stops = []
    for index in range(draw(st.integers(2, 25))):
        segment = draw(st.sampled_from(grid.segments()))
        (x0, y0), (x1, y1) = (grid.projection.to_xy(p) for p in segment.geometry)
        length = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        f = draw(st.floats(0.3, 0.7))
        off = draw(st.floats(4.0, 15.0)) * draw(st.sampled_from([1.0, -1.0]))
        point = grid.projection.to_lonlat(
            x0 + ux * length * f - uy * off, y0 + uy * length * f + ux * off
        )
        result = snapper.snap(StopPoint(f"s{index}", point))
        if isinstance(result, SnappedStop):
            stops.append(result)
    nodes = list(range(size * size))
    sites = RouteSites(
        Place("yard", draw(st.sampled_from(nodes))), Place("disposal", draw(st.sampled_from(nodes)))
    )
    capacity = draw(st.none() | st.integers(3, 10))
    carts_on_streets = len({s.segment_id for s in stops})
    trucks = draw(st.integers(1, max(1, min(3, carts_on_streets))))
    return Area(graph, tuple(stops), sites), trucks, TruckProfile(capacity_carts=capacity)


@given(areas())
@settings_(deadline=None)
def test_n_routes_cover_every_servable_stop_once(problem):
    area, trucks, profile = problem
    if not area.stops:
        return
    fleet = FleetSettings(trucks, solve=SolveSettings(profile, solution_limit=SMALL))
    result = solve_routes(area, fleet)  # the checker runs inside and raises on any breach
    assert len(result.routes) == trucks
    picked = [p.stop_id for r in result.routes for p in r.route.pickups]
    unserved = [u.stop_id for u in result.unserved]
    assert sorted(picked + unserved) == sorted(s.stop_id for s in area.stops)
    if picked:
        assert all(r.route.pickups for r in result.routes)
    assert result.total_bound_ms <= result.total_ms
    assert result.longest_bound_ms <= result.longest_ms or not picked


@given(areas())
@settings_(deadline=None)
def test_one_truck_is_the_single_route_solver(problem):
    area, _, profile = problem
    if not area.stops:
        return
    settings = SolveSettings(profile, solution_limit=SMALL)
    fleet = solve_routes(area, FleetSettings(1, solve=settings))
    single = optimize(area.graph, area.stops, area.sites, settings)
    assert fleet.routes[0].plan == single.plan


@given(areas())
@settings_(deadline=None)
def test_the_same_area_gives_the_same_routes(problem):
    area, trucks, profile = problem
    if not area.stops:
        return
    fleet = FleetSettings(trucks, solve=SolveSettings(profile, solution_limit=SMALL))
    assert solve_routes(area, fleet) == solve_routes(area, fleet)


@given(areas())
@settings_(deadline=None)
def test_the_exchange_never_makes_the_route_set_worse(problem):
    area, trucks, profile = problem
    if not area.stops:
        return
    solve = SolveSettings(profile, solution_limit=SMALL)
    without = solve_routes(area, FleetSettings(trucks, solve=solve, exchange=False))
    with_exchange = solve_routes(area, FleetSettings(trucks, solve=solve))
    assert with_exchange.key <= without.key


@given(areas())
@settings_(deadline=None)
def test_no_district_is_split_on_a_connected_grid(problem):
    area, trucks, profile = problem
    if not area.stops:
        return
    result = solve_routes(
        area, FleetSettings(trucks, solve=SolveSettings(profile, solution_limit=SMALL))
    )
    if result.unserved:
        return  # the units below would then differ from the ones the districts were built on
    units = build_units(area.graph, Counter(s.required_pass for s in area.stops))
    members = defaultdict(set)
    for u, d in result.district_of.items():
        members[d].add(u)
    for d in range(trucks):
        assert pieces(units, members[d]) == 1, d


def _small_area() -> Area:
    grid = Grid()
    graph = build_state_graph(grid.segments())
    snapper = Snapper(graph)
    stops = tuple(
        r
        for k, (x, y) in enumerate([(30, -10), (170, -10), (30, 290), (230, 290)])
        if isinstance(r := snapper.snap(StopPoint(f"s{k}", grid.at(x, y))), SnappedStop)
    )
    return Area(graph, stops, RouteSites(Place("yard", 0), Place("disposal", 15)))


def test_the_checker_rejects_a_stop_served_twice():
    area = _small_area()
    settings = SolveSettings(solution_limit=SMALL)
    result = solve_routes(area, FleetSettings(2, solve=settings))
    first, second = result.routes
    stolen = first.route.pickups[0]
    doubled = replace(
        second,
        route=replace(
            second.route, pickups=(*second.route.pickups, Pickup(stolen.stop_id, 0, 0.0, False))
        ),
    )
    broken = replace(result, routes=(first, doubled))
    allowed = u_turn_nodes(area.graph, area.stops, settings.rules)
    with pytest.raises(RouteSetError):
        check_route_set(area, settings, broken, allowed)


def test_the_checker_rejects_a_wrong_side_pickup():
    area = _small_area()
    settings = SolveSettings(solution_limit=SMALL)
    result = solve_routes(area, FleetSettings(1, solve=settings))
    (route,) = result.routes
    flipped = replace(route.route.pickups[0], wrong_side=True)
    broken = replace(
        result,
        routes=(
            replace(route, route=replace(route.route, pickups=(flipped, *route.route.pickups[1:]))),
        ),
    )
    allowed = u_turn_nodes(area.graph, area.stops, settings.rules)
    with pytest.raises(RouteSetError, match="from the right"):
        check_route_set(area, settings, broken, allowed)


def test_the_total_objective_without_a_maximum_duration_is_refused():
    area = _small_area()
    fleet = FleetSettings(
        2, objective=RouteObjective.TOTAL, solve=SolveSettings(solution_limit=SMALL)
    )
    with pytest.raises(ValueError, match="maximum route duration"):
        solve_routes(area, fleet)
