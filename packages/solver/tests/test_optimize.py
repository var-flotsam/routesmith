import pytest

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.graph import Place, SnappedStop, StreetSegment
from starboard.solver.optimize import (
    RouteSites,
    SolveSettings,
    TruckProfile,
    UnservedReason,
    optimize,
)
from starboard.solver.route import PlaceVisit
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
    assert len(result.route.pickups) == 8
    unloads = [v for v in result.route.place_visits if v.unload]
    assert len(unloads) >= 2
    card = score(GRAPH, result.route)
    assert card.disposal_visits == len(unloads)


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
    assert all(isinstance(v, PlaceVisit) for v in warm.route.place_visits)
