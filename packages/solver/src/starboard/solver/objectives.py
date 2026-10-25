"""What "best" means for several routes in one area, and how far from best a result may be.

The owner's choice (ADR-0003) is `balanced-total`: least total route time
with every route within `defaults.BALANCE_MARGIN` of the average. The other
two are options. Candidates are compared by an acceptance key in integer
milliseconds, compared lexicographically; a smaller key is better. Every key
starts with the time over the truck's maximum route duration, so that limit
bounds every route under every objective.
"""

from collections.abc import Sequence
from enum import StrEnum

from starboard.solver import defaults
from starboard.solver.connections import UNREACHABLE, ConnectionCosts, traversal_ms
from starboard.solver.graph import Pass, StateGraph
from starboard.solver.route import RouteSites

_MS_PER_S = 1000


class RouteObjective(StrEnum):
    BALANCED_TOTAL = "balanced-total"
    LONGEST_ROUTE = "longest-route"
    TOTAL = "total"


def check_objective(objective: RouteObjective, max_route_duration_s: float | None) -> None:
    """Refuse `total` without a maximum route duration.

    Least total time alone drifts to one long route and token others, since each
    extra truck adds only its own yard and disposal legs.
    """
    if objective is RouteObjective.TOTAL and max_route_duration_s is None:
        raise ValueError("the total objective needs a maximum route duration")


def acceptance_key(
    objective: RouteObjective,
    route_ms: Sequence[int],
    max_route_ms: int | None = None,
    margin: float | None = None,
) -> tuple[int, ...]:
    """The comparison key for one set of route times; smaller is better."""
    total = sum(route_ms)
    over = 0 if max_route_ms is None else sum(max(0, t - max_route_ms) for t in route_ms)
    if objective is RouteObjective.TOTAL:
        return (over, total)
    if objective is RouteObjective.LONGEST_ROUTE:
        return (over, max(route_ms, default=0), total)
    return (over, balance_excess_ms(route_ms, margin), total)


def balance_excess_ms(route_ms: Sequence[int], margin: float | None = None) -> int:
    """Total time by which routes fall outside the balance margin around the average."""
    if not route_ms:
        return 0
    m = defaults.BALANCE_MARGIN.value if margin is None else margin
    mean = sum(route_ms) / len(route_ms)
    return round(sum(max(0.0, abs(t - mean) - m * mean) for t in route_ms))


def lower_bounds_ms(
    graph: StateGraph,
    connections: ConnectionCosts,
    sites: RouteSites,
    carts_on: dict[Pass, int],
    trucks: int,
) -> tuple[int, int]:
    """Lower bounds on the total and on the longest of `trucks` route times.

    Every route drives and services its passes, leaves the yard onto some
    required pass, leaves its last pass for the disposal site, unloads, and
    returns to the yard, so the total is at least the sum of all service plus
    `trucks` times the cheapest of each leg. No route can be shorter than the
    single costliest yard, pass, disposal, yard trip, or than the average.
    Passes must be anchors of `connections`, which must include both sites.
    """
    if not carts_on:
        return 0, 0
    cart_ms = round(defaults.CART_SERVICE_TIME.value * _MS_PER_S)
    unload_ms = round(defaults.DISPOSAL_UNLOAD_TIME.value * _MS_PER_S)
    service = {p: traversal_ms(graph, p) + n * cart_ms for p, n in carts_on.items()}
    leave = [connections.from_place(sites.yard, p) for p in carts_on]
    finish = [connections.to_place(p, sites.disposal) for p in carts_on]
    home = connections.between_places(sites.disposal, sites.yard)
    if UNREACHABLE in (*leave, *finish, home):
        raise ValueError("every required pass must be reachable from the yard and reach disposal")
    fixed = min(leave) + min(finish) + unload_ms + home
    total = sum(service.values()) + trucks * fixed
    single = max(
        lv + service[p] + fn + unload_ms + home
        for p, lv, fn in zip(carts_on, leave, finish, strict=True)
    )
    return total, max(single, -(-total // trucks))


def gap(found_ms: int, bound_ms: int) -> float:
    """How far a result may be from best: (found - bound) / bound, 0 when they meet."""
    return 0.0 if bound_ms <= 0 else max(0.0, (found_ms - bound_ms) / bound_ms)
