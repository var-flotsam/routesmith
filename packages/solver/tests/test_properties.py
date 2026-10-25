"""Hard constraints, property-tested on random synthetic grids.

The current-route baseline is held to the driving constraints every route
must meet: no travel against a one-way, no restricted turn, and no U-turn
the routing rules forbid. Every expected value here is worked out from the
graph and stops directly, not by calling the code under test. The optimized
route is held to all four hard constraints of CLAUDE.md.
"""

import math
from collections import defaultdict, deque
from dataclasses import dataclass, replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver import defaults
from starboard.solver.baseline import build_baseline
from starboard.solver.graph import (
    Direction,
    LonLat,
    Pass,
    Place,
    SnappedStop,
    StateGraph,
    StreetSegment,
)
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import DrivenRoute, PlaceVisit, RouteSites, TruckProfile
from starboard.solver.rules import RoutingRules, UTurnPolicy
from starboard.solver.scorecard import score

pytestmark = pytest.mark.property

ROAD_CLASSES = ["residential", "service", "unclassified", "tertiary", "secondary"]
QUIET = {"residential", "unclassified", "living_street", "service"}  # the rule, restated
STUB_LENGTH_M = 80.0


@dataclass(frozen=True)
class Scenario:
    graph: StateGraph
    stops: list[SnappedStop]
    rules: RoutingRules
    listed_street: dict[str, str]  # stop id -> the street the list puts it on


def spellings(name: str) -> list[str]:
    """Ways one street's name is written on a list."""
    short = name.replace(" Street", " St").replace(" Avenue", " Ave").replace(" Court", " Ct")
    return [name, short, name.lower(), short.upper() + "."]


@st.composite
def networks(draw: st.DrawFn) -> tuple[Grid, list[StreetSegment]]:
    size = draw(st.integers(3, 5))
    rows = list(range(size))
    east = draw(st.sets(st.sampled_from(rows), max_size=2))
    west = draw(st.sets(st.sampled_from([r for r in rows if r not in east]), max_size=2))
    grid = Grid(size=size, one_way_east=frozenset(east), one_way_west=frozenset(west))
    segments = [
        replace(s, road_class=draw(st.sampled_from(ROAD_CLASSES))) if draw(st.booleans()) else s
        for s in grid.segments()
    ]
    # Dead-end spurs south from the bottom row, some on busy road classes.
    for index, col in enumerate(draw(st.sets(st.integers(0, size - 1), max_size=2))):
        x = col * grid.block_m
        segments.append(
            StreetSegment(
                segment_id=f"stub-{index}",
                from_node=grid.node(0, col),
                to_node=10_000 + index,
                geometry=(grid.at(x, 0.0), grid.at(x, -STUB_LENGTH_M)),
                length_m=STUB_LENGTH_M,
                name=f"Stub {index} Court",
                forward_allowed=True,
                reverse_allowed=True,
                road_class=draw(st.sampled_from(ROAD_CLASSES)),
                osm_way_ids=(90_000 + index,),
            )
        )
    return grid, segments


def point_beside(grid: Grid, segment: StreetSegment, fraction: float, offset: float) -> LonLat:
    (x0, y0), (x1, y1) = (grid.projection.to_xy(p) for p in segment.geometry)
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    x = x0 + ux * length * fraction - uy * offset
    y = y0 + uy * length * fraction + ux * offset
    return grid.projection.to_lonlat(x, y)


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    grid, segments = draw(networks())
    graph = build_state_graph(segments)
    restrictions = [
        TurnRestriction(
            graph.segments[t.from_pass.segment_id].osm_way_ids[0],
            t.via_node,
            graph.segments[t.to_pass.segment_id].osm_way_ids[0],
            RestrictionKind.PROHIBITORY,
        )
        for t in draw(st.lists(st.sampled_from(graph.transitions), max_size=4, unique=True))
    ]
    graph = build_state_graph(segments, restrictions=restrictions)

    # Single stops anywhere, and sometimes a dense cluster on one street.
    placements: list[StreetSegment] = draw(st.lists(st.sampled_from(segments), max_size=10))
    if draw(st.booleans()):
        cluster_on = draw(st.sampled_from(segments))
        placements[draw(st.integers(0, len(placements))) : 0] = [cluster_on] * draw(
            st.integers(7, 15)
        )

    snapper = Snapper(graph)
    stops: list[SnappedStop] = []
    listed_street: dict[str, str] = {}
    for index, segment in enumerate(placements):
        fraction = draw(st.floats(0.3, 0.7))
        offset = draw(st.floats(3.0, 20.0)) * draw(st.sampled_from([1.0, -1.0]))
        assert segment.name is not None
        address = draw(st.none() | st.sampled_from(spellings(segment.name)))
        stop_id = f"s{index}"
        result = snapper.snap(
            StopPoint(stop_id, point_beside(grid, segment, fraction, offset), street=address)
        )
        if isinstance(result, SnappedStop):
            stops.append(result)
            snapped_name = graph.segments[result.segment_id].name
            listed_street[stop_id] = segment.name if address else (snapped_name or "")
    rules = RoutingRules(u_turns=draw(st.sampled_from(list(UTurnPolicy))))
    return Scenario(graph, stops, rules, listed_street)


def allowed_u_turn(scenario: Scenario, node: int) -> bool:
    """Whether the rules allow a U-turn at `node`, worked out from scratch."""
    graph, rules = scenario.graph, scenario.rules
    touching = [
        s for s in graph.segments.values() for end in (s.from_node, s.to_node) if end == node
    ]
    if len(touching) == 1:
        return True  # a dead end
    if rules.u_turns is UTurnPolicy.ANYWHERE:
        return True
    if rules.u_turns is UTurnPolicy.DEAD_ENDS_ONLY:
        return False
    stops_on = defaultdict(int)
    for stop in scenario.stops:
        stops_on[stop.segment_id] += 1
    for segment in touching:
        window_km = max(segment.length_m, defaults.U_TURN_DENSITY_WINDOW.value) / 1000
        if segment.road_class not in QUIET:
            return False
        if stops_on[segment.segment_id] / window_km >= defaults.U_TURN_MAX_STOP_DENSITY.value:
            return False
    return True


@given(scenarios())
def test_the_baseline_drives_only_legal_passes_and_turns(scenario):
    graph = scenario.graph
    route = build_baseline(graph, scenario.stops, scenario.rules)
    nodes = {n for s in graph.segments.values() for n in (s.from_node, s.to_node)}
    assert route.u_turn_nodes == {n for n in nodes if allowed_u_turn(scenario, n)}
    passes = set(graph.passes)
    transitions = set(graph.transitions)

    assert len(route.joins) == max(len(route.traversals) - 1, 0)
    assert route.joins == route.transitions  # the current route visits no place
    for traversal in route.traversals:
        assert traversal.on_pass in passes  # never against a one-way
        length = graph.segments[traversal.on_pass.segment_id].length_m
        assert 0.0 <= traversal.start_m <= traversal.end_m <= length + 1e-9
    for index, transition in enumerate(route.transitions):
        assert transition in transitions
        assert not transition.forbidden_by_restriction
        if transition.is_u_turn:
            assert allowed_u_turn(scenario, transition.via_node)
        assert transition.from_pass == route.traversals[index].on_pass
        assert transition.to_pass == route.traversals[index + 1].on_pass
        assert route.traversals[index].end_m == pytest.approx(
            graph.segments[transition.from_pass.segment_id].length_m
        )
        assert route.traversals[index + 1].start_m == 0.0


def _path_distance(
    route: DrivenRoute, earlier: tuple[int, float], later: tuple[int, float]
) -> float:
    """Distance driven from one point on the route to a later one."""
    (i, at_i), (j, at_j) = earlier, later
    if i == j:
        return at_j - at_i
    distance = route.traversals[i].end_m - at_i
    distance += sum(t.end_m - t.start_m for t in route.traversals[i + 1 : j])
    return distance + at_j - route.traversals[j].start_m


def _reachable_after(scenario: Scenario, start: Pass) -> set[Pass]:
    """Every pass the truck can enter after leaving `start`, under the rules."""
    outgoing = defaultdict(list)
    for t in scenario.graph.transitions:
        if t.forbidden_by_restriction or (t.is_u_turn and not allowed_u_turn(scenario, t.via_node)):
            continue
        outgoing[t.from_pass].append(t.to_pass)
    seen: set[Pass] = set()
    queue = deque(outgoing[start])
    while queue:
        current = queue.popleft()
        if current not in seen:
            seen.add(current)
            queue.extend(outgoing[current])
    return seen


@given(scenarios())
def test_the_baseline_services_each_street_in_list_order_and_each_stop_once(scenario):
    graph, stops = scenario.graph, scenario.stops
    route = build_baseline(graph, stops, scenario.rules)
    by_id = {s.stop_id: s for s in stops}
    unreachable = set(route.unreachable_stop_ids)
    picked = [p.stop_id for p in route.pickups]
    assert len(picked) == len(set(picked))
    assert set(picked) | unreachable == set(by_id)
    assert not set(picked) & unreachable

    # Streets come in list order, however their names are spelled; within a street,
    # any order.
    runs: list[set[str]] = []
    previous = None
    for stop in stops:
        street = scenario.listed_street[stop.stop_id].casefold()
        if street != previous:
            runs.append(set())
            previous = street
        runs[-1].add(stop.stop_id)
    position = 0
    for run in (r - unreachable for r in runs):
        assert set(picked[position : position + len(run)]) == run
        position += len(run)
    assert position == len(picked)

    serviced = sorted(stop_id for t in route.traversals for stop_id in t.serviced_stop_ids)
    assert serviced == sorted(picked)

    # A stop is only unreachable if the truck truly cannot get to it.
    legal = set(graph.passes)
    if route.traversals:
        last = route.traversals[-1]
        after = _reachable_after(scenario, last.on_pass)
        for stop_id in unreachable:
            stop = by_id[stop_id]
            candidates = {Pass(stop.segment_id, d) for d in Direction} & legal
            assert not candidates & after, stop_id
            if last.on_pass in candidates:  # only if it is behind where the truck stopped
                length = graph.segments[stop.segment_id].length_m
                along = min(max(stop.distance_along_m, 0.0), length)
                at = along if last.on_pass.direction is Direction.FORWARD else length - along
                assert at < last.end_m, stop_id
    else:
        for stop_id in unreachable:
            assert not {Pass(by_id[stop_id].segment_id, d) for d in Direction} & legal

    truck = None  # the furthest point reached so far
    for pickup in route.pickups:
        stop = by_id[pickup.stop_id]
        traversal = route.traversals[pickup.traversal_index]
        # The stop is collected where it is, from the pass the truck was on.
        assert traversal.on_pass.segment_id == stop.segment_id
        assert traversal.start_m - 1e-6 <= pickup.at_m <= traversal.end_m + 1e-6
        length = graph.segments[stop.segment_id].length_m
        along = min(max(stop.distance_along_m, 0.0), length)
        expected_at = along if traversal.on_pass.direction is Direction.FORWARD else length - along
        assert pickup.at_m == pytest.approx(expected_at)
        assert pickup.wrong_side == (traversal.on_pass != stop.required_pass)
        # A stop behind the truck is only ever one it passed within the pass-by window.
        point = (pickup.traversal_index, pickup.at_m)
        if truck is None or point >= truck:
            truck = point
        else:
            assert _path_distance(route, point, truck) <= defaults.PASS_BY_DISTANCE.value + 1e-6


@given(scenarios())
def test_route_time_is_driving_plus_collection_plus_wrong_side_extra(scenario):
    card = score(scenario.graph, build_baseline(scenario.graph, scenario.stops, scenario.rules))
    assert card.service_time_s == pytest.approx(
        card.stops_serviced * defaults.CART_SERVICE_TIME.value
    )
    assert card.wrong_side_time_s == pytest.approx(
        card.wrong_side_pickups * defaults.WRONG_SIDE_PICKUP_TIME.value
    )
    assert card.route_time_s == pytest.approx(
        card.drive_time_s + card.service_time_s + card.wrong_side_time_s
    )


def _check_joins(scenario: Scenario, route: DrivenRoute) -> None:
    """Each join is a legal turn, or a visit to the node one pass ends and the next starts at."""
    graph = scenario.graph
    transitions = set(graph.transitions)
    assert len(route.joins) == max(len(route.traversals) - 1, 0)
    for index, join in enumerate(route.joins):
        before, after = route.traversals[index], route.traversals[index + 1]
        if isinstance(join, PlaceVisit):
            assert _pass_ends(graph, before.on_pass)[1] == join.place.node
            assert before.end_m == pytest.approx(graph.segments[before.on_pass.segment_id].length_m)
            assert _pass_ends(graph, after.on_pass)[0] == join.place.node
            assert after.start_m == 0.0
            continue
        assert join in transitions
        assert not join.forbidden_by_restriction
        if join.is_u_turn:
            assert allowed_u_turn(scenario, join.via_node)
        assert (join.from_pass, join.to_pass) == (before.on_pass, after.on_pass)


def _check_yard_to_yard(
    scenario: Scenario, route: DrivenRoute, sites: RouteSites, capacity: int | None
) -> None:
    """Starts at the yard, unloads before the end and whenever full, ends at the yard."""
    graph = scenario.graph
    if not route.pickups:
        return
    assert route.start == sites.yard and route.end == sites.yard
    first, last = route.traversals[0], route.traversals[-1]
    assert _pass_ends(graph, first.on_pass)[0] == sites.yard.node and first.start_m == 0.0
    end_node = sites.disposal.node if route.closing_visits else sites.yard.node
    assert _pass_ends(graph, last.on_pass)[1] == end_node
    if route.closing_visits:
        assert sites.disposal.node == sites.yard.node
    unload_points = [i for i, j in enumerate(route.joins) if isinstance(j, PlaceVisit) and j.unload]
    unload_points += [len(route.traversals) - 1] * sum(v.unload for v in route.closing_visits)
    assert unload_points, "the route never visits the disposal site"
    assert max(p.traversal_index for p in route.pickups) <= max(unload_points)
    collected_by = defaultdict(int)
    for pickup in route.pickups:
        collected_by[pickup.traversal_index] += 1
    load, unloads_after = 0, sorted(unload_points)
    for index in range(len(route.traversals)):
        load += collected_by[index]
        if capacity is not None:
            assert load <= capacity
        while unloads_after and unloads_after[0] == index:
            load = 0
            unloads_after.pop(0)


@st.composite
def current_routes_with_sites(draw: st.DrawFn) -> tuple[Scenario, RouteSites, TruckProfile]:
    scenario = draw(scenarios())
    nodes = sorted({n for s in scenario.graph.segments.values() for n in (s.from_node, s.to_node)})
    sites = RouteSites(
        Place("yard", draw(st.sampled_from(nodes))),
        Place("disposal", draw(st.sampled_from(nodes))),
    )
    return scenario, sites, TruckProfile(capacity_carts=draw(st.none() | st.integers(1, 8)))


@given(current_routes_with_sites())
def test_the_current_route_with_sites_drives_yard_to_yard_legally(problem):
    scenario, sites, profile = problem
    try:
        route = build_baseline(
            scenario.graph, scenario.stops, scenario.rules, sites=sites, profile=profile
        )
    except ValueError:
        assert not _yard_reachable_from_disposal(scenario, sites)
        return
    _check_joins(scenario, route)
    unreachable = set(route.unreachable_stop_ids)
    assert {p.stop_id for p in route.pickups} | unreachable == {s.stop_id for s in scenario.stops}
    _check_yard_to_yard(scenario, route, sites, profile.capacity_carts)


# The optimized route: invariants 1 to 4 (CLAUDE.md) on every route the solver returns.

TEST_SOLUTION_LIMIT = 40  # a small search keeps each example quick; the invariants hold at any size


@st.composite
def routing_problems(draw: st.DrawFn) -> tuple[Scenario, RouteSites, TruckProfile]:
    scenario = draw(scenarios())
    nodes = sorted({n for s in scenario.graph.segments.values() for n in (s.from_node, s.to_node)})
    yard = Place("yard", draw(st.sampled_from(nodes)))
    disposal = Place("disposal", draw(st.sampled_from(nodes)))
    capacity = draw(st.none() | st.integers(1, 8))
    return scenario, RouteSites(yard, disposal), TruckProfile(capacity_carts=capacity)


def _settings(scenario: Scenario, profile: TruckProfile) -> SolveSettings:
    return SolveSettings(profile, scenario.rules, TEST_SOLUTION_LIMIT)


def _yard_reachable_from_disposal(scenario: Scenario, sites: RouteSites) -> bool:
    """Worked out from scratch: some legal drive leads from the disposal site to the yard."""
    graph = scenario.graph
    if sites.disposal.node == sites.yard.node:
        return True
    starts = [p for p in graph.passes if _pass_ends(graph, p)[0] == sites.disposal.node]
    seen = set(starts)
    for p in starts:
        seen |= _reachable_after(scenario, p)
    return any(_pass_ends(graph, p)[1] == sites.yard.node for p in seen)


def _solve(scenario: Scenario, sites: RouteSites, profile: TruckProfile):
    """The optimized route, or None when the sites leave no way back to the yard."""
    try:
        return optimize(scenario.graph, scenario.stops, sites, _settings(scenario, profile))
    except ValueError:
        assert not _yard_reachable_from_disposal(scenario, sites)
        return None


def _pass_ends(graph: StateGraph, p: Pass) -> tuple[int, int]:
    s = graph.segments[p.segment_id]
    return (
        (s.from_node, s.to_node) if p.direction is Direction.FORWARD else (s.to_node, s.from_node)
    )


@given(routing_problems())
def test_every_optimized_route_meets_the_hard_constraints(problem):
    scenario, sites, profile = problem
    graph, stops = scenario.graph, scenario.stops
    result = _solve(scenario, sites, profile)
    if result is None:
        return
    route = result.route
    by_id = {s.stop_id: s for s in stops}
    unserved = {u.stop_id for u in result.unserved}
    passes = set(graph.passes)
    transitions = set(graph.transitions)

    # Every servable stop is collected exactly once.
    picked = [p.stop_id for p in route.pickups]
    assert len(picked) == len(set(picked))
    assert set(picked) | unserved == set(by_id)
    assert not set(picked) & unserved

    # 1. Every serviced cart is on the truck's right at the moment of service.
    for pickup in route.pickups:
        traversal = route.traversals[pickup.traversal_index]
        assert not pickup.wrong_side
        assert traversal.on_pass == by_id[pickup.stop_id].required_pass

    # 2. No travel against a one-way. 3. No U-turn or restricted turn the rules forbid.
    assert len(route.joins) == max(len(route.traversals) - 1, 0)
    for traversal in route.traversals:
        assert traversal.on_pass in passes
        length = graph.segments[traversal.on_pass.segment_id].length_m
        assert traversal.start_m == 0.0 and traversal.end_m == pytest.approx(length)
    for index, join in enumerate(route.joins):
        before, after = route.traversals[index].on_pass, route.traversals[index + 1].on_pass
        if isinstance(join, PlaceVisit):
            assert _pass_ends(graph, before)[1] == join.place.node
            assert _pass_ends(graph, after)[0] == join.place.node
            continue
        assert join in transitions
        assert not join.forbidden_by_restriction
        if join.is_u_turn:
            assert allowed_u_turn(scenario, join.via_node)
        assert (join.from_pass, join.to_pass) == (before, after)

    # 4. Starts at the yard, unloads before the end and whenever the next pass would
    # overfill the truck, and ends at the yard.
    if not route.pickups:
        return
    assert route.start == sites.yard and route.end == sites.yard
    assert _pass_ends(graph, route.traversals[0].on_pass)[0] == sites.yard.node
    if route.closing_visits:
        assert sites.disposal.node == sites.yard.node
        assert _pass_ends(graph, route.traversals[-1].on_pass)[1] == sites.disposal.node
    else:
        assert _pass_ends(graph, route.traversals[-1].on_pass)[1] == sites.yard.node
    unload_points = [i for i, j in enumerate(route.joins) if isinstance(j, PlaceVisit) and j.unload]
    unload_points += [len(route.traversals) - 1] * sum(v.unload for v in route.closing_visits)
    assert unload_points, "the route never visits the disposal site"
    assert max(p.traversal_index for p in route.pickups) <= max(unload_points)
    load = 0
    unloads_after = sorted(unload_points)
    for index, traversal in enumerate(route.traversals):
        load += len(traversal.serviced_stop_ids)
        if profile.capacity_carts is not None:
            assert load <= profile.capacity_carts
        while unloads_after and unloads_after[0] == index:
            load = 0
            unloads_after.pop(0)


@given(routing_problems())
def test_the_plan_cost_is_the_scorecard_route_time(problem):
    scenario, sites, profile = problem
    result = _solve(scenario, sites, profile)
    if result is None:
        return
    card = score(scenario.graph, result.route)
    assert card.wrong_side_pickups == 0
    assert card.route_time_s == pytest.approx(
        result.plan.cost_ms / 1000, abs=0.01 * max(1, len(result.route.traversals))
    )


@given(routing_problems())
def test_the_same_input_gives_the_same_route(problem):
    scenario, sites, profile = problem
    first, second = (_solve(scenario, sites, profile) for _ in range(2))
    assert first == second
