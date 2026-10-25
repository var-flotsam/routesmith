import math
from dataclasses import replace

import pytest

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver import defaults
from starboard.solver.graph import SnappedStop, StreetSegment
from starboard.solver.rules import RoutingRules, UTurnPolicy, u_turn_nodes

GRID = Grid()
STUB_END = 999
LOW_DENSITY = RoutingRules(UTurnPolicy.LOW_DENSITY)


def stub(road_class: str = "residential") -> StreetSegment:
    """A 100 m two-way spur south from the grid's south-west corner, ending in a dead end."""
    return StreetSegment(
        segment_id="stub",
        from_node=GRID.node(0, 0),
        to_node=STUB_END,
        geometry=(GRID.at(0, 0), GRID.at(0, -GRID.block_m)),
        length_m=GRID.block_m,
        name="Stub Court",
        forward_allowed=True,
        reverse_allowed=True,
        road_class=road_class,
    )


def stops_along(graph, segment_id: str, count: int) -> list[SnappedStop]:
    """`count` stops spread along one curb of a 100 m segment, away from its ends."""
    snapper = Snapper(graph)
    (x0, y0), (x1, y1) = (GRID.projection.to_xy(p) for p in graph.segments[segment_id].geometry)
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    stops = []
    for index in range(count):
        along = 30.0 + 40.0 * index / max(count - 1, 1)
        x, y = x0 + ux * along + uy * 10.0, y0 + uy * along - ux * 10.0  # right-hand curb
        result = snapper.snap(StopPoint(f"{segment_id}-{index}", GRID.projection.to_lonlat(x, y)))
        assert isinstance(result, SnappedStop), result
        stops.append(result)
    return stops


def dense_count() -> int:
    """The fewest stops that make a 100 m street dense, measured over the density window."""
    window_km = max(GRID.block_m, defaults.U_TURN_DENSITY_WINDOW.value) / 1000
    return math.ceil(defaults.U_TURN_MAX_STOP_DENSITY.value * window_km)


@pytest.mark.parametrize("policy", list(UTurnPolicy))
def test_a_dead_end_always_allows_a_u_turn(policy):
    graph = build_state_graph([*GRID.segments(), stub(road_class="secondary")])
    dense = stops_along(graph, "stub", dense_count() + 2)
    assert graph.dead_end_nodes == frozenset({STUB_END})
    assert STUB_END in u_turn_nodes(graph, dense, RoutingRules(policy))


def test_dead_ends_only_allows_exactly_the_dead_ends():
    graph = build_state_graph([*GRID.segments(), stub()])
    allowed = u_turn_nodes(graph, [], RoutingRules(UTurnPolicy.DEAD_ENDS_ONLY))
    assert allowed == frozenset({STUB_END})


def test_anywhere_allows_every_node():
    graph = build_state_graph([*GRID.segments(), stub()])
    allowed = u_turn_nodes(graph, [], RoutingRules(UTurnPolicy.ANYWHERE))
    assert allowed == frozenset({*range(GRID.size * GRID.size), STUB_END})


def test_low_density_forbids_the_ends_of_a_dense_street_only():
    graph = build_state_graph(GRID.segments())
    dense = stops_along(graph, "h-0-0", dense_count())
    sparse = dense[:-1]
    assert dense_count() == 13  # 32 stops/km over a quarter mile
    allowed = u_turn_nodes(graph, dense, LOW_DENSITY)
    assert GRID.node(0, 0) not in allowed
    assert GRID.node(0, 1) not in allowed
    assert GRID.node(0, 2) in allowed
    assert GRID.node(0, 1) in u_turn_nodes(graph, sparse, LOW_DENSITY)


def test_low_density_judges_each_street_not_the_average_at_the_node():
    # One dense block and three empty ones meet at node (1, 1): pooled over 400 m the
    # density would be low, but the dense block alone is a residence district.
    graph = build_state_graph(GRID.segments())
    dense = stops_along(graph, "v-0-1", dense_count())
    assert GRID.node(1, 1) not in u_turn_nodes(graph, dense, LOW_DENSITY)


def test_low_density_never_allows_a_node_on_a_busy_road():
    segments = [
        replace(s, road_class="secondary") if s.segment_id == "v-0-1" else s
        for s in GRID.segments()
    ]
    graph = build_state_graph(segments)
    allowed = u_turn_nodes(graph, [], LOW_DENSITY)
    assert GRID.node(0, 1) not in allowed
    assert GRID.node(1, 1) not in allowed
    assert GRID.node(0, 0) in allowed
