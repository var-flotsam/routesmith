import pytest

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver import defaults
from starboard.solver.baseline import build_baseline
from starboard.solver.graph import Direction, Pass, SnappedStop
from starboard.solver.rules import RoutingRules, UTurnPolicy
from starboard.solver.scorecard import score

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())
SNAPPER = Snapper(GRAPH)
DEAD_ENDS_ONLY = RoutingRules(u_turns=UTurnPolicy.DEAD_ENDS_ONLY)
ANYWHERE = RoutingRules(u_turns=UTurnPolicy.ANYWHERE)


def stop(stop_id: str, x: float, y: float, street: str | None = None) -> SnappedStop:
    """A stop snapped on the default grid; `street` is the street its address names."""
    result = SNAPPER.snap(StopPoint(stop_id, GRID.at(x, y), street=street))
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
    route = build_baseline(GRAPH, [first, second], DEAD_ENDS_ONLY)
    assert route.wrong_side_stop_ids == ("b",)
    card = score(GRAPH, route)
    assert card.wrong_side_pickups == 1
    assert card.wrong_side_time_s == defaults.WRONG_SIDE_PICKUP_TIME.value


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
    assert card.service_time_s == 2 * defaults.CART_SERVICE_TIME.value
    assert card.route_time_s == pytest.approx(card.drive_time_s + card.service_time_s)


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
    # The next stop is 60 m behind on the north curb, beyond pick-up-in-passing range.
    # With U-turns allowed the truck turns at the next node; without, it loops the block.
    a = stop("a", 80, -10)
    b = stop("b", 20, 10)
    without = build_baseline(GRAPH, [a, b], DEAD_ENDS_ONLY)
    with_u_turns = build_baseline(GRAPH, [a, b], ANYWHERE)
    assert not any(t.is_u_turn for t in without.transitions)
    assert any(t.is_u_turn for t in with_u_turns.transitions)
    assert score(GRAPH, with_u_turns).distance_m < score(GRAPH, without).distance_m


def test_a_stop_just_behind_on_the_right_is_picked_up_in_passing():
    # b's address is on another list entry's street, so it comes after a on the list.
    start = stop("start", 25, -10, "A Street")
    a = stop("a", 60, -10, "A Street")
    b = stop("b", 45, -10, "B Street")  # 15 m behind, same curb: driven past on the way to a
    route = build_baseline(GRAPH, [start, a, b], DEAD_ENDS_ONLY)
    assert len(route.traversals) == 1
    assert route.traversals[0].serviced_stop_ids == ("start", "a", "b")
    assert route.transitions == ()
    assert route.wrong_side_stop_ids == ()


def test_a_stop_just_behind_on_the_left_is_picked_up_in_passing_as_wrong_side():
    start = stop("start", 25, -10, "A Street")
    a = stop("a", 60, -10, "A Street")
    b = stop("b", 45, 10, "B Street")  # 15 m behind, opposite curb: looping costs more
    route = build_baseline(GRAPH, [start, a, b], DEAD_ENDS_ONLY)
    assert route.transitions == ()
    assert route.wrong_side_stop_ids == ("b",)


def test_a_stop_passed_just_before_an_intersection_is_picked_up_in_passing():
    start = stop("start", 70, -10, "A Street")  # row 0, first block, eastbound
    b_before_node = stop("b", 88, 4, "B Street")  # north curb, 12 m before the node
    a = stop("a", 112, -4, "A Street")  # 12 m past the node, on the next block
    route = build_baseline(GRAPH, [start, a, b_before_node], DEAD_ENDS_ONLY)
    assert [p.stop_id for p in route.pickups] == ["start", "a", "b"]
    assert route.pickups[2].traversal_index == 0  # collected on the block it was passed on
    assert route.wrong_side_stop_ids == ("b",)
    assert len(route.transitions) == 1


def test_a_stop_far_behind_is_not_picked_up_in_passing():
    start = stop("start", 25, -10, "A Street")
    a = stop("a", 80, -10, "A Street")
    b = stop("b", 30, -10, "B Street")  # 50 m behind: beyond the pass-by window
    route = build_baseline(GRAPH, [start, a, b], DEAD_ENDS_ONLY)
    assert route.transitions  # the truck goes round to reach it


def test_the_truck_turns_round_when_that_beats_a_wrong_side_pickup():
    # Next stop is 40 m ahead on the left. Getting out costs the wrong-side time;
    # with U-turns allowed, turning at the next node and coming back is quicker.
    a = stop("a", 20, -10)
    b = stop("b", 60, 10)
    turned = build_baseline(GRAPH, [a, b], ANYWHERE)
    assert turned.wrong_side_stop_ids == ()
    assert any(t.is_u_turn for t in turned.transitions)
    stuck = build_baseline(GRAPH, [a, b], DEAD_ENDS_ONLY)
    assert stuck.wrong_side_stop_ids == ("b",)


def test_dead_head_is_distance_on_passes_that_service_nothing():
    a = stop("a", 50, -10)
    b = stop("b", 250, 210)  # far corner: some passes in between service nothing
    route = build_baseline(GRAPH, [a, b])
    card = score(GRAPH, route)
    empty = [t for t in route.traversals if not t.serviced_stop_ids]
    assert empty
    assert card.dead_head_m == pytest.approx(sum(t.end_m - t.start_m for t in empty))


def test_a_streets_stops_are_collected_in_the_order_the_truck_reaches_them():
    # Listed out of position order, as two-sided house numbering often is.
    stops = [stop("start", 25, -10), stop("a", 80, -10), stop("b", 40, -10), stop("c", 60, -10)]
    route = build_baseline(GRAPH, stops, DEAD_ENDS_ONLY)
    assert [p.stop_id for p in route.pickups] == ["start", "b", "c", "a"]
    assert route.transitions == ()


def test_streets_are_driven_in_list_order():
    # Column 1 is listed first even though row 0 is where the truck starts nearer.
    stops = [stop("start", 25, -10), stop("col", 110, 150), stop("row", 60, -10)]
    route = build_baseline(GRAPH, stops, DEAD_ENDS_ONLY)
    assert [p.stop_id for p in route.pickups] == ["start", "col", "row"]


def test_one_street_over_two_blocks_is_one_run():
    # Row 0 Street spans h-0-0 and h-0-1; listed out of position order.
    stops = [stop("m1", 150, -10), stop("m2", 50, -10), stop("m3", 170, -10)]
    route = build_baseline(GRAPH, stops, DEAD_ENDS_ONLY)
    assert [p.stop_id for p in route.pickups] == ["m1", "m3", "m2"]


def test_spellings_of_one_street_are_one_run():
    # "Row 0 St", a blank address (the OSM name "Row 0 Street") and "ROW 0 ST." match.
    stops = [
        stop("start", 25, -10, "Row 0 St"),
        stop("a", 80, -10),
        stop("b", 40, -10, "ROW 0 ST."),
    ]
    route = build_baseline(GRAPH, stops, DEAD_ENDS_ONLY)
    assert [p.stop_id for p in route.pickups] == ["start", "b", "a"]
    assert route.transitions == ()
