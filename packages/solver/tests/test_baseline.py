import pytest

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.baseline import RoutingRules, build_baseline
from starboard.solver.graph import Direction, Pass, SnappedStop
from starboard.solver.scorecard import score

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())
SNAPPER = Snapper(GRAPH)


def stop(stop_id: str, x: float, y: float, graph=GRAPH) -> SnappedStop:
    result = (SNAPPER if graph is GRAPH else Snapper(graph)).snap(StopPoint(stop_id, GRID.at(x, y)))
    assert isinstance(result, SnappedStop), result
    return result


def test_stops_ahead_on_the_same_pass_are_one_traversal():
    # South curb of row 0 is on the right when driving east.
    stops = [stop("a", 20, -10), stop("b", 60, -10), stop("c", 80, -10)]
    route = build_baseline(GRAPH, stops)
    assert len(route.traversals) == 1
    (traversal,) = route.traversals
    assert traversal.on_pass == Pass("h-0-0", Direction.FORWARD)
    assert traversal.serviced_stop_ids == ("a", "b", "c")
    assert traversal.end_m - traversal.start_m == pytest.approx(60.0, abs=0.01)
    assert route.wrong_side_stop_ids == ()


def test_a_stop_reached_with_the_cart_on_the_left_counts_as_wrong_side():
    # The truck services the south curb heading east; the next stop is just ahead on
    # the north curb. Driving on is far quicker than looping round to come back
    # westbound, so that cart is picked up from the left.
    first = stop("a", 20, -10)
    second = stop("b", 60, 10)
    assert second.required_pass == Pass("h-0-0", Direction.REVERSE)
    route = build_baseline(GRAPH, [first, second])
    assert route.wrong_side_stop_ids == ("b",)
    assert score(GRAPH, route).wrong_side_pickups == 1


def test_a_left_turn_is_counted_and_costed():
    a = stop("a", 50, -10)  # row 0 south curb: eastbound pass
    b = stop("b", 110, 50)  # column 1 east curb: northbound pass
    route = build_baseline(GRAPH, [a, b])
    card = score(GRAPH, route)
    assert [t.to_pass for t in route.transitions] == [Pass("v-0-1", Direction.FORWARD)]
    assert card.left_turns == 1
    assert card.right_turns == 0
    assert card.distance_m == pytest.approx(100.0, abs=0.01)
    # 100 m at 25 km/h = 14.4 s, plus a 90-degree turn (7.5 s) and the left-turn extra (2 s).
    assert card.drive_time_s == pytest.approx(14.4 + 7.5 + 2.0, abs=0.01)
    assert card.wrong_side_pickups == 0
    assert card.dead_head_m == 0.0
    assert card.street_passes == 2
    assert card.stops_serviced == 2


def test_the_route_never_takes_a_restricted_turn():
    a = stop("a", 50, -10)
    b = stop("b", 110, 50)
    no_left = TurnRestriction(
        Grid.way_id("h-0-0"), GRID.node(0, 1), Grid.way_id("v-0-1"), RestrictionKind.PROHIBITORY
    )
    restricted = build_state_graph(GRID.segments(), restrictions=[no_left])
    route = build_baseline(restricted, [a, b])
    assert route.transitions
    assert not any(t.forbidden_by_restriction for t in route.transitions)
    assert score(restricted, route).distance_m > 100.0


def test_u_turns_follow_the_routing_rules():
    # A stop behind the truck on the same street: with intersection U-turns allowed
    # the truck turns around at the next node; without, it drives round the block.
    a = stop("a", 60, -10)
    b = stop("b", 40, 10)
    without = build_baseline(GRAPH, [a, b])
    with_u_turns = build_baseline(GRAPH, [a, b], RoutingRules(u_turns_at_intersections=True))
    assert not any(t.is_u_turn for t in without.transitions)
    assert any(t.is_u_turn for t in with_u_turns.transitions)
    assert score(GRAPH, with_u_turns).distance_m < score(GRAPH, without).distance_m


def test_dead_head_is_distance_on_passes_that_service_nothing():
    a = stop("a", 50, -10)
    b = stop("b", 250, 210)  # far corner: some passes in between service nothing
    route = build_baseline(GRAPH, [a, b])
    card = score(GRAPH, route)
    empty = [t for t in route.traversals if not t.serviced_stop_ids]
    assert empty
    assert card.dead_head_m == pytest.approx(sum(t.end_m - t.start_m for t in empty))
