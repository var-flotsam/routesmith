"""Hard constraints, property-tested on random synthetic grids.

The current-route baseline is held to the driving constraints every route
must meet: no travel against a one-way, no restricted turn, and no U-turn
the routing rules forbid. Solver output joins these tests in phase 3.
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.baseline import RoutingRules, build_baseline
from starboard.solver.graph import SnappedStop, StateGraph

pytestmark = pytest.mark.property


@st.composite
def grids(draw: st.DrawFn) -> Grid:
    size = draw(st.integers(3, 5))
    rows = list(range(size))
    east = draw(st.sets(st.sampled_from(rows), max_size=2))
    west = draw(st.sets(st.sampled_from([r for r in rows if r not in east]), max_size=2))
    return Grid(size=size, one_way_east=frozenset(east), one_way_west=frozenset(west))


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[StateGraph, list[SnappedStop], RoutingRules]:
    grid = draw(grids())
    segments = grid.segments()
    graph = build_state_graph(segments)
    restrictions = [
        TurnRestriction(
            Grid.way_id(t.from_pass.segment_id),
            t.via_node,
            Grid.way_id(t.to_pass.segment_id),
            RestrictionKind.PROHIBITORY,
        )
        for t in draw(st.lists(st.sampled_from(graph.transitions), max_size=4, unique=True))
    ]
    graph = build_state_graph(segments, restrictions=restrictions)

    snapper = Snapper(graph)
    stops: list[SnappedStop] = []
    projection = grid.projection
    for index in range(draw(st.integers(1, 12))):
        segment = draw(st.sampled_from(segments))
        fraction = draw(st.floats(0.3, 0.7))
        offset = draw(st.floats(3.0, 20.0)) * draw(st.sampled_from([1.0, -1.0]))
        (x0, y0), (x1, y1) = (projection.to_xy(p) for p in segment.geometry)
        length = math.hypot(x1 - x0, y1 - y0)
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        x, y = x0 + ux * length * fraction - uy * offset, y0 + uy * length * fraction + ux * offset
        result = snapper.snap(StopPoint(f"s{index}", projection.to_lonlat(x, y)))
        if isinstance(result, SnappedStop):
            stops.append(result)
    rules = RoutingRules(u_turns_at_intersections=draw(st.booleans()))
    return graph, stops, rules


@given(scenarios())
def test_the_baseline_drives_only_legal_passes_and_turns(scenario):
    graph, stops, rules = scenario
    route = build_baseline(graph, stops, rules)
    passes = set(graph.passes)
    transitions = set(graph.transitions)

    assert len(route.transitions) == max(len(route.traversals) - 1, 0)
    for traversal in route.traversals:
        assert traversal.on_pass in passes  # never against a one-way
        length = graph.segments[traversal.on_pass.segment_id].length_m
        assert 0.0 <= traversal.start_m <= traversal.end_m <= length + 1e-9
    for index, transition in enumerate(route.transitions):
        assert transition in transitions
        assert not transition.forbidden_by_restriction
        if transition.is_u_turn:
            assert rules.u_turns_at_intersections or transition.via_node in graph.dead_end_nodes
        assert transition.from_pass == route.traversals[index].on_pass
        assert transition.to_pass == route.traversals[index + 1].on_pass
        assert route.traversals[index].end_m == pytest.approx(
            graph.segments[transition.from_pass.segment_id].length_m
        )
        assert route.traversals[index + 1].start_m == 0.0


@given(scenarios())
def test_the_baseline_services_every_reachable_stop_once_in_order(scenario):
    graph, stops, rules = scenario
    route = build_baseline(graph, stops, rules)
    serviced = [stop_id for t in route.traversals for stop_id in t.serviced_stop_ids]
    unreachable = set(route.unreachable_stop_ids)
    assert serviced == [s.stop_id for s in stops if s.stop_id not in unreachable]

    servicing_pass = {
        stop_id: t.on_pass for t in route.traversals for stop_id in t.serviced_stop_ids
    }
    expected_wrong_side = [
        s.stop_id
        for s in stops
        if s.stop_id in servicing_pass and servicing_pass[s.stop_id] != s.required_pass
    ]
    assert list(route.wrong_side_stop_ids) == expected_wrong_side
