"""Driven paths: the right stretch of each street, in driving order, with no repeats."""

import pytest

from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.graph import Direction, Pass
from starboard.solver.paths import driven_path, stretch
from starboard.solver.route import DrivenRoute, Traversal

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())


def _xy(point):
    return GRID.projection.to_xy(type(GRID.at(0, 0))(lon=point[0], lat=point[1]))


def _route(*traversals):
    joins = tuple(range(len(traversals) - 1))  # paths read traversals only
    return DrivenRoute(tuple(traversals), joins, (), (), frozenset())


def test_a_whole_pass_is_the_segment_end_to_end():
    segment = GRAPH.segments["h-0-0"]
    line = stretch(segment.geometry, segment.length_m, 0.0, segment.length_m)
    assert _xy(line[0]) == pytest.approx((0.0, 0.0), abs=0.1)
    assert _xy(line[-1]) == pytest.approx((100.0, 0.0), abs=0.1)


def test_a_part_pass_stops_where_the_truck_stopped():
    segment = GRAPH.segments["h-0-0"]
    line = stretch(segment.geometry, segment.length_m, 20.0, 60.0)
    assert _xy(line[0]) == pytest.approx((20.0, 0.0), abs=0.1)
    assert _xy(line[-1]) == pytest.approx((60.0, 0.0), abs=0.1)


def test_a_route_is_drawn_in_driving_order_without_repeating_corners():
    route = _route(
        Traversal(Pass("h-0-0", Direction.FORWARD), 0.0, 100.0, ()),
        Traversal(Pass("v-0-1", Direction.FORWARD), 0.0, 100.0, ()),
        Traversal(Pass("h-1-0", Direction.REVERSE), 0.0, 100.0, ()),
    )
    path = [_xy(p) for p in driven_path(GRAPH, route)]
    expected = [(0, 0), (100, 0), (100, 100), (0, 100)]
    assert len(path) == len(expected)
    for got, want in zip(path, expected, strict=True):
        assert got == pytest.approx(want, abs=0.1)
