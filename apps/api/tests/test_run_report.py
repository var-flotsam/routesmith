"""The API's run report model takes exactly what the solver's comparison produces."""

from starboard.api.routers.runs import RunReport
from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.comparison import ComparisonRequest, compare
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites


def test_the_solver_report_fits_the_api_model():
    grid = Grid()
    graph = build_state_graph(grid.segments())
    snapper = Snapper(graph)
    stops = [snapper.snap(StopPoint(f"s{k}", grid.at(x, -10))) for k, x in enumerate((20, 60))]
    assert all(isinstance(s, SnappedStop) for s in stops)
    request = ComparisonRequest(
        1, RouteObjective.BALANCED_TOTAL, SolveSettings(solution_limit=30), {}
    )
    report = compare(graph, stops, RouteSites(Place("yard", 0), Place("disposal", 0)), request)
    report["osm_snapshot"] = "2026-10-01"
    parsed = RunReport.model_validate(report)
    assert parsed.model_dump(mode="json") == report
