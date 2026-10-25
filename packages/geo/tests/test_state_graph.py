import pytest
from grid import BLOCK_M, at, grid_segments, node, way_id

from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.solver.graph import Direction, Pass, StreetSegment


@pytest.fixture(scope="module")
def graph():
    return build_state_graph(grid_segments())


def test_one_pass_per_legal_direction(graph):
    # 24 segments, of which rows 1 and 2 (6 segments) are one-way.
    assert len(graph.segments) == 24
    assert len(graph.passes) == 18 * 2 + 6


def test_no_pass_against_a_one_way(graph):
    directions = {(p.segment_id, p.direction) for p in graph.passes}
    for col in range(3):
        assert (f"h-1-{col}", Direction.REVERSE) not in directions
        assert (f"h-2-{col}", Direction.FORWARD) not in directions


def test_transitions_join_passes_at_their_shared_node(graph):
    def ends(state: Pass) -> tuple[int, int]:
        segment = graph.segments[state.segment_id]
        forward = (segment.from_node, segment.to_node)
        return forward if state.direction is Direction.FORWARD else forward[::-1]

    assert graph.transitions
    for transition in graph.transitions:
        assert ends(transition.from_pass)[1] == transition.via_node
        assert ends(transition.to_pass)[0] == transition.via_node


def test_u_turns_are_flagged_and_reverse_the_heading(graph):
    for transition in graph.transitions:
        same_segment = transition.from_pass.segment_id == transition.to_pass.segment_id
        assert transition.is_u_turn == same_segment
        if transition.is_u_turn:
            assert transition.heading_change_deg == pytest.approx(180.0, abs=1e-6)


def test_heading_change_is_positive_for_right_turns(graph):
    arriving = Pass("h-1-0", Direction.FORWARD)  # eastbound into node (1, 1)
    changes = {
        t.to_pass: t.heading_change_deg for t in graph.transitions if t.from_pass == arriving
    }
    assert changes[Pass("h-1-1", Direction.FORWARD)] == pytest.approx(0.0, abs=1e-6)
    assert changes[Pass("v-1-1", Direction.FORWARD)] == pytest.approx(-90.0, abs=1e-6)  # north
    assert changes[Pass("v-0-1", Direction.REVERSE)] == pytest.approx(90.0, abs=1e-6)  # south


def test_dead_ends_are_nodes_with_one_segment():
    stub = StreetSegment(
        segment_id="stub",
        from_node=node(0, 0),
        to_node=999,
        geometry=(at(0, 0), at(0, -BLOCK_M)),
        length_m=BLOCK_M,
        name="Stub Court",
        forward_allowed=True,
        reverse_allowed=True,
    )
    graph = build_state_graph([*grid_segments(), stub])
    assert graph.dead_end_nodes == frozenset({999})
    turnaround = [t for t in graph.transitions if t.via_node == 999]
    assert [t.is_u_turn for t in turnaround] == [True]


def test_output_does_not_depend_on_input_order():
    segments = grid_segments()
    assert build_state_graph(segments) == build_state_graph(list(reversed(segments)))


def _forbidden_from(graph, arriving: Pass) -> dict[Pass, bool]:
    return {
        t.to_pass: t.forbidden_by_restriction for t in graph.transitions if t.from_pass == arriving
    }


def test_a_prohibitory_restriction_forbids_exactly_that_turn():
    no_left = TurnRestriction(
        way_id("h-1-0"), node(1, 1), way_id("v-1-1"), RestrictionKind.PROHIBITORY
    )
    graph = build_state_graph(grid_segments(), restrictions=[no_left])
    forbidden = _forbidden_from(graph, Pass("h-1-0", Direction.FORWARD))
    assert forbidden == {
        Pass("h-1-1", Direction.FORWARD): False,
        Pass("v-1-1", Direction.FORWARD): True,
        Pass("v-0-1", Direction.REVERSE): False,
    }
    assert sum(t.forbidden_by_restriction for t in graph.transitions) == 1


def test_a_mandatory_restriction_forbids_every_other_turn():
    only_straight = TurnRestriction(
        way_id("h-0-0"), node(0, 1), way_id("h-0-1"), RestrictionKind.MANDATORY
    )
    graph = build_state_graph(grid_segments(), restrictions=[only_straight])
    forbidden = _forbidden_from(graph, Pass("h-0-0", Direction.FORWARD))
    assert forbidden == {
        Pass("h-0-0", Direction.REVERSE): True,  # the U-turn
        Pass("h-0-1", Direction.FORWARD): False,
        Pass("v-0-1", Direction.FORWARD): True,
    }


def test_a_restriction_at_another_node_changes_nothing():
    elsewhere = TurnRestriction(
        way_id("h-1-0"), node(3, 3), way_id("v-1-1"), RestrictionKind.PROHIBITORY
    )
    graph = build_state_graph(grid_segments(), restrictions=[elsewhere])
    assert not any(t.forbidden_by_restriction for t in graph.transitions)


def test_cut_off_nodes_are_not_dead_ends():
    stub = StreetSegment(
        segment_id="stub",
        from_node=node(0, 0),
        to_node=999,
        geometry=(at(0, 0), at(0, -BLOCK_M)),
        length_m=BLOCK_M,
        name="Edge Road",
        forward_allowed=True,
        reverse_allowed=True,
    )
    graph = build_state_graph([*grid_segments(), stub], cut_off_nodes=frozenset({999}))
    assert graph.dead_end_nodes == frozenset()
