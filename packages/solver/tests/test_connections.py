"""Connection costs against an independent Dijkstra over the same rules."""

import heapq
from collections import defaultdict

import pytest
from hypothesis import given
from hypothesis import strategies as st

from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import (
    UNREACHABLE,
    ConnectionCosts,
    traversal_ms,
    turn_ms,
)
from starboard.solver.graph import Direction, Pass, Place, StateGraph
from starboard.solver.rules import RoutingRules, UTurnPolicy, u_turn_nodes


def ends(graph: StateGraph, p: Pass) -> tuple[int, int]:
    s = graph.segments[p.segment_id]
    return (
        (s.from_node, s.to_node) if p.direction is Direction.FORWARD else (s.to_node, s.from_node)
    )


def oracle(graph: StateGraph, allowed_u: frozenset[int], source: Pass) -> dict[Pass, int]:
    """Cost from the end of `source` to the start of every pass, by plain Dijkstra."""
    out = defaultdict(list)
    for t in graph.transitions:
        if t.forbidden_by_restriction or (t.is_u_turn and t.via_node not in allowed_u):
            continue
        out[t.from_pass].append(t)
    best: dict[Pass, int] = {}
    heap = [
        (turn_ms(t), t.to_pass.segment_id, t.to_pass.direction.value, t.to_pass)
        for t in out[source]
    ]
    heapq.heapify(heap)
    while heap:
        cost, _, _, p = heapq.heappop(heap)
        if p in best:
            continue
        best[p] = cost
        for t in out[p]:
            if t.to_pass not in best:
                nxt = cost + traversal_ms(graph, p) + turn_ms(t)
                heapq.heappush(
                    heap, (nxt, t.to_pass.segment_id, t.to_pass.direction.value, t.to_pass)
                )
    return best


@st.composite
def networks(draw):
    size = draw(st.integers(3, 5))
    rows = list(range(size))
    east = draw(st.sets(st.sampled_from(rows), max_size=2))
    west = draw(st.sets(st.sampled_from([r for r in rows if r not in east]), max_size=2))
    grid = Grid(size=size, one_way_east=frozenset(east), one_way_west=frozenset(west))
    segments = grid.segments()
    plain = build_state_graph(segments)
    restricted = draw(st.lists(st.sampled_from(plain.transitions), max_size=5, unique=True))
    graph = build_state_graph(
        segments,
        restrictions=[
            TurnRestriction(
                Grid.way_id(t.from_pass.segment_id),
                t.via_node,
                Grid.way_id(t.to_pass.segment_id),
                RestrictionKind.PROHIBITORY,
            )
            for t in restricted
        ],
    )
    policy = draw(st.sampled_from(list(UTurnPolicy)))
    allowed_u = u_turn_nodes(graph, [], RoutingRules(policy))
    anchors = draw(st.lists(st.sampled_from(graph.passes), min_size=1, max_size=6, unique=True))
    yard = Place("yard", draw(st.integers(0, size * size - 1)))
    disposal = Place("disposal", draw(st.integers(0, size * size - 1)))
    return graph, allowed_u, anchors, yard, disposal


@given(networks())
def test_costs_between_passes_match_an_independent_dijkstra(network):
    graph, allowed_u, anchors, _, _ = network
    costs = ConnectionCosts(graph, allowed_u, anchors)
    for a in anchors:
        expected = oracle(graph, allowed_u, a)
        for b in graph.passes:
            if b == a:
                continue
            assert costs.between(a, b) == expected.get(b, UNREACHABLE), (a, b)


@given(networks())
def test_paths_are_legal_and_add_up_to_their_cost(network):
    graph, allowed_u, anchors, yard, disposal = network
    costs = ConnectionCosts(graph, allowed_u, anchors, [yard, disposal])
    transitions = set(graph.transitions)

    def check_chain(start: Pass, path, end: Pass) -> int:
        cost, current = 0, start
        for t in path:
            assert t in transitions
            assert t.from_pass == current
            assert not t.forbidden_by_restriction
            assert not t.is_u_turn or t.via_node in allowed_u
            cost += (traversal_ms(graph, current) if current != start else 0) + turn_ms(t)
            current = t.to_pass
        assert current == end
        return cost

    for a in anchors:
        for b in anchors:
            if a != b and costs.between(a, b) != UNREACHABLE:
                assert check_chain(a, costs.path_between(a, b), b) == costs.between(a, b)
        if costs.to_place(a, disposal) != UNREACHABLE:
            path = costs.path_to_place(a, disposal)
            last = path[-1].to_pass if path else a
            assert ends(graph, last)[1] == disposal.node
            total = check_chain(a, path, last) + (traversal_ms(graph, last) if path else 0)
            assert total == costs.to_place(a, disposal)
        if costs.from_place(yard, a) != UNREACHABLE:
            first, path = costs.path_from_place(yard, a)
            assert ends(graph, first)[0] == yard.node
            # check_chain leaves out the first pass's own traversal; add it back.
            chain = check_chain(first, path, a)
            expected = chain + (traversal_ms(graph, first) if first != a else 0)
            assert expected == costs.from_place(yard, a)


def test_leaving_and_reaching_the_same_place_costs_nothing():
    graph = build_state_graph(Grid().segments())
    yard = Place("yard", 0)
    costs = ConnectionCosts(graph, frozenset(), [], [yard])
    assert costs.between_places(yard, yard) == 0
    assert costs.path_between_places(yard, yard) == (None, ())


def test_a_pass_to_itself_is_refused():
    graph = build_state_graph(Grid().segments())
    p = graph.passes[0]
    with pytest.raises(ValueError, match="different passes"):
        ConnectionCosts(graph, frozenset(), [p]).between(p, p)
