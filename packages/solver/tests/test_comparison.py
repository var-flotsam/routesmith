"""The run report: both sides scored, every stop accounted for, plain JSON values."""

import json

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.comparison import ComparisonRequest, compare
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())
SITES = RouteSites(Place("yard", 0), Place("disposal", 0))


def _stops():
    snapper = Snapper(GRAPH)
    points = [(20, -10), (60, -10), (30, 290), (230, 290)]
    snapped = [snapper.snap(StopPoint(f"s{k}", GRID.at(x, y))) for k, (x, y) in enumerate(points)]
    assert all(isinstance(s, SnappedStop) for s in snapped)
    return snapped


def _request(trucks, route_of=None):
    return ComparisonRequest(
        trucks, RouteObjective.BALANCED_TOTAL, SolveSettings(solution_limit=30), route_of or {}
    )


def test_one_truck_against_the_whole_list():
    report = compare(GRAPH, _stops(), SITES, _request(1))
    assert [r["route_id"] for r in report["current"]["routes"]] == [None]
    assert report["current"]["area"]["stops_serviced"] == 4
    assert report["optimized"]["area"]["stops_serviced"] == 4
    assert report["total_lower_bound_s"] <= report["total_route_time_s"]
    json.dumps(report)  # plain values only


def test_current_routes_by_id_against_two_trucks():
    route_of = {"s0": "B", "s1": "B", "s2": "A", "s3": "A"}
    report = compare(GRAPH, _stops(), SITES, _request(2, route_of))
    assert [r["route_id"] for r in report["current"]["routes"]] == ["A", "B"]
    orders = [r["order"] for r in report["optimized"]["routes"]]
    assert sorted(s for order in orders for s in order) == ["s0", "s1", "s2", "s3"]
