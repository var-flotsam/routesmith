"""Current against optimized for one area: what a run reports.

`compare` drives today's routes (one per current route id, or one for the
whole list), solves the area for the given number of trucks, scores both, and
returns everything as plain JSON-ready values. It is pure, like the rest of the
solver: the caller supplies the network, the snapped stops and the sites.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any  # the report is plain JSON values

from starboard.solver.baseline import build_baseline, current_routes, routes_by_id
from starboard.solver.fleet import Area, FleetSettings, solve_routes
from starboard.solver.graph import SnappedStop, StateGraph
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites
from starboard.solver.scorecard import Scorecard, area_scorecard, score

_MS_PER_S = 1000


@dataclass(frozen=True, slots=True)
class ComparisonRequest:
    """The stops in current order; `route_of` names each stop's current route, if known."""

    trucks: int
    objective: RouteObjective
    settings: SolveSettings
    route_of: Mapping[str, str]


def compare(
    graph: StateGraph,
    stops: Sequence[SnappedStop],
    sites: RouteSites,
    request: ComparisonRequest,
) -> dict[str, Any]:
    """The run report: current and optimized scorecards, orders, bounds and unserved stops."""
    settings = request.settings
    current: list[tuple[str | None, Scorecard]]
    if request.route_of:
        by_route = routes_by_id(stops, request.route_of)
        driven = current_routes(graph, by_route, settings.rules, sites, settings.profile)
        current = [(route_id, score(graph, r)) for route_id, r in driven.items()]
    else:
        route = build_baseline(graph, stops, settings.rules, sites, settings.profile)
        current = [(None, score(graph, route))]
    fleet = FleetSettings(request.trucks, request.objective, settings)
    result = solve_routes(Area(graph, tuple(stops), sites), fleet, warm_start=stops)
    optimized = [
        (score(graph, r.route), [p.stop_id for p in r.route.pickups]) for r in result.routes
    ]
    return {
        "trucks": request.trucks,
        "objective": request.objective.value,
        "current": {
            "routes": [{"route_id": k, "scorecard": asdict(card)} for k, card in current],
            "area": asdict(area_scorecard([card for _, card in current])),
        },
        "optimized": {
            "routes": [{"scorecard": asdict(card), "order": order} for card, order in optimized],
            "area": asdict(area_scorecard([card for card, _ in optimized])),
        },
        "total_route_time_s": result.total_ms / _MS_PER_S,
        "longest_route_time_s": result.longest_ms / _MS_PER_S,
        "total_lower_bound_s": result.total_bound_ms / _MS_PER_S,
        "gap": result.gap,
        "balance_met": result.balance_met,
        "unserved": [{"stop_id": u.stop_id, "reason": u.reason.value} for u in result.unserved],
        "time_limited": any(r.time_limited for r in result.routes),
    }
