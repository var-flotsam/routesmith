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
from starboard.solver.graph import Direction, Pass, Place, StateGraph, Transition
from starboard.solver.route import PlaceVisit
from starboard.solver.rules import RoutingRules, UTurnPolicy, u_turn_nodes

# Going in and out of a place costs 2 ms in the search graph (one ms in, one out).
PASS_THROUGH_MS = 2


def ends(graph: StateGraph, p: Pass) -> tuple[int, int]:
    s = graph.segments[p.segment_id]
    return (
        (s.from_node, s.to_node) if p.direction is Direction.FORWARD else (s.to_node, s.from_node)
    )


def oracle(
    graph: StateGraph, allowed_u: frozenset[int], source: Pass, places: list[Place]
) -> dict[Pass, int]:
    """Cost from the end of `source` to the start of every pass, by plain Dijkstra.

    At a place node the truck may also turn onto any pass starting there, at no turn cost:
    the free turnaround inside the yard or disposal site.
    """
    out: dict[Pass, list[tuple[Pass, int]]] = defaultdict(list)
    for t in graph.transitions:
        if t.forbidden_by_restriction or (t.is_u_turn and t.via_node not in allowed_u):
            continue
        out[t.from_pass].append((t.to_pass, turn_ms(t)))
    place_nodes = {p.node for p in places}
    for a in graph.passes:
        if ends(graph, a)[1] in place_nodes:
            for b in graph.passes:
                if ends(graph, b)[0] == ends(graph, a)[1]:
                    out[a].append((b, PASS_THROUGH_MS))
    best: dict[Pass, int] = {}
    heap = [(cost, b.segment_id, b.direction.value, b) for b, cost in out[source]]
    heapq.heapify(heap)
    while heap:
        cost, _, _, p = heapq.heappop(heap)
        if p in best:
            continue
        best[p] = cost
        for b, step in out[p]:
            if b not in best:
                nxt = cost + traversal_ms(graph, p) + step
                heapq.heappush(heap, (nxt, b.segment_id, b.direction.value, b))
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
    graph, allowed_u, anchors, yard, disposal = network
    for places in ([], [yard, disposal]):
        costs = ConnectionCosts(graph, allowed_u, anchors, places)
        for a in anchors:
            expected = oracle(graph, allowed_u, a, places)
            for b in graph.passes:
                if b != a:
                    assert costs.between(a, b) == expected.get(b, UNREACHABLE), (a, b, places)
        matrix = costs.between_all(anchors)
        for i, a in enumerate(anchors):
            for j, b in enumerate(anchors):
                assert matrix[i, j] == (UNREACHABLE if a == b else costs.between(a, b))


def _walk_cost(graph, allowed_u, start: Pass, steps, transitions) -> tuple[int, Pass]:
    """Check each step is legal; return the cost from the end of `start` and the last pass."""
    cost, current = 0, start
    for join, next_pass in steps:
        if isinstance(join, Transition):
            assert join in transitions
            assert join.from_pass == current and join.to_pass == next_pass
            assert not join.forbidden_by_restriction
            assert not join.is_u_turn or join.via_node in allowed_u
            step = turn_ms(join)
        else:
            assert isinstance(join, PlaceVisit) and not join.unload
            assert ends(graph, current)[1] == join.place.node == ends(graph, next_pass)[0]
            step = PASS_THROUGH_MS
        cost += (traversal_ms(graph, current) if current != start else 0) + step
        current = next_pass
    return cost, current


@given(networks())
def test_paths_are_legal_and_add_up_to_their_cost(network):
    graph, allowed_u, anchors, yard, disposal = network
    costs = ConnectionCosts(graph, allowed_u, anchors, [yard, disposal])
    transitions = set(graph.transitions)

    for a in anchors:
        for b in anchors:
            if a != b and costs.between(a, b) != UNREACHABLE:
                cost, last = _walk_cost(graph, allowed_u, a, costs.path_between(a, b), transitions)
                assert last == b
                assert cost == costs.between(a, b)
        if costs.to_place(a, disposal) != UNREACHABLE:
            steps = costs.path_to_place(a, disposal)
            cost, last = _walk_cost(graph, allowed_u, a, steps, transitions)
            assert ends(graph, last)[1] == disposal.node
            total = cost + (traversal_ms(graph, last) if steps else 0)
            assert total == costs.to_place(a, disposal)
        if costs.from_place(yard, a) != UNREACHABLE:
            first, steps = costs.path_from_place(yard, a)
            assert ends(graph, first)[0] == yard.node
            cost, last = _walk_cost(graph, allowed_u, first, steps, transitions)
            assert last == a
            # The cost counts driving the first pass, which the walk leaves out.
            total = cost + (traversal_ms(graph, first) if steps else 0)
            assert total == costs.from_place(yard, a)


def test_a_turnaround_inside_a_place_is_used_when_the_street_forbids_it():
    # With no U-turns allowed on the street, turning round inside the disposal site at
    # the far end of a block is quicker than driving round the block.
    grid = Grid()
    graph = build_state_graph(grid.segments())
    there = Pass("h-0-0", Direction.FORWARD)
    back = Pass("h-0-0", Direction.REVERSE)
    place = Place("disposal", grid.node(0, 1))
    without = ConnectionCosts(graph, frozenset(), [there], [])
    with_place = ConnectionCosts(graph, frozenset(), [there], [place])
    assert with_place.between(there, back) < without.between(there, back)
    steps = with_place.path_between(there, back)
    assert [type(join) for join, _ in steps] == [PlaceVisit]


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
