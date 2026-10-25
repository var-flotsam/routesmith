from collections import Counter

from hypothesis import given
from hypothesis import strategies as st

from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import UNREACHABLE, ConnectionCosts
from starboard.solver.graph import Direction, Pass, StreetSegment
from starboard.solver.units import build_units, unit_distance_ms, workload_ms

GRID = Grid()


def lane(segment_id: str, start: int, end: int, x0: float, x1: float) -> StreetSegment:
    """A two-way stretch of Stub Lane south of the grid, running east."""
    return StreetSegment(
        segment_id=segment_id,
        from_node=start,
        to_node=end,
        geometry=(GRID.at(x0, -100.0), GRID.at(x1, -100.0)),
        length_m=x1 - x0,
        name="Stub Lane",
        forward_allowed=True,
        reverse_allowed=True,
        road_class="residential",
    )


def with_lane():
    # Stub Lane: node 900 -- 901 -- 902, joined to the grid at node 0 by a spur.
    spur = StreetSegment(
        segment_id="spur",
        from_node=GRID.node(0, 0),
        to_node=900,
        geometry=(GRID.at(0, 0), GRID.at(0, -100.0)),
        length_m=100.0,
        name="Spur Road",
        forward_allowed=True,
        reverse_allowed=True,
        road_class="residential",
    )
    return build_state_graph(
        [
            *GRID.segments(),
            spur,
            lane("lane-a", 900, 901, 0, 100),
            lane("lane-b", 901, 902, 100, 200),
        ]
    )


@given(
    st.dictionaries(st.sampled_from(build_state_graph(GRID.segments()).passes), st.integers(1, 5))
)
def test_every_segment_is_in_exactly_one_unit_with_both_curbs(carts_on):
    graph = build_state_graph(GRID.segments())
    units = build_units(graph, carts_on)
    counted = Counter(sid for u in units.units for sid in u.segment_ids)
    assert set(counted) == set(graph.segments) and set(counted.values()) == {1}
    unit_of = {sid: u for u in units.units for sid in u.segment_ids}
    for p in carts_on:
        assert p in unit_of[p.segment_id].required_passes
    assert sum(u.carts for u in units.units) == sum(carts_on.values())
    for u, near in units.neighbours.items():
        for v in near:
            assert u in units.neighbours[v]
            assert units.by_id[u].nodes & units.by_id[v].nodes


def test_a_street_through_a_two_way_node_is_one_unit():
    graph = with_lane()
    carts = {Pass("lane-a", Direction.FORWARD): 2, Pass("lane-b", Direction.REVERSE): 1}
    units = build_units(graph, carts)
    (lane_unit,) = [u for u in units.units if "lane-a" in u.segment_ids]
    assert lane_unit.segment_ids == ("lane-a", "lane-b")
    assert lane_unit.carts == 3


def test_a_street_with_carts_on_part_of_it_is_two_units():
    graph = with_lane()
    units = build_units(graph, {Pass("lane-a", Direction.FORWARD): 2})
    lane_units = [u for u in units.units if {"lane-a", "lane-b"} & set(u.segment_ids)]
    assert sorted(u.segment_ids for u in lane_units) == [("lane-a",), ("lane-b",)]
    assert [u.is_connector for u in sorted(lane_units, key=lambda u: u.unit_id)] == [False, True]


def test_grid_intersections_split_streets_into_blocks():
    graph = build_state_graph(GRID.segments())
    units = build_units(graph, {})
    assert len(units.units) == len(graph.segments)
    assert all(u.is_connector for u in units.units)


def test_unit_distance_is_the_quicker_of_the_two_orders():
    graph = build_state_graph(GRID.segments())
    carts = {Pass("h-0-0", Direction.FORWARD): 1, Pass("h-3-2", Direction.FORWARD): 1}
    units = build_units(graph, carts)
    a = next(u for u in units.units if "h-0-0" in u.segment_ids)
    b = next(u for u in units.units if "h-3-2" in u.segment_ids)
    connections = ConnectionCosts(graph, frozenset(), list(carts))
    there = connections.between(Pass("h-0-0", Direction.FORWARD), Pass("h-3-2", Direction.FORWARD))
    back = connections.between(Pass("h-3-2", Direction.FORWARD), Pass("h-0-0", Direction.FORWARD))
    assert there != UNREACHABLE and back != UNREACHABLE
    assert unit_distance_ms(connections, graph, a, b) == min(there, back)
    assert unit_distance_ms(connections, graph, b, a) == min(there, back)


def test_workload_grows_with_carts():
    graph = build_state_graph(GRID.segments())
    p = Pass("h-0-0", Direction.FORWARD)
    small = build_units(graph, {p: 1}).units
    large = build_units(graph, {p: 5}).units
    w_small = max(workload_ms(graph, u) for u in small)
    w_large = max(workload_ms(graph, u) for u in large)
    assert w_large > w_small > 0
