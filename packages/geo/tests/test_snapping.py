import math

import pytest
from grid import BLOCK_M, PROJECTION, at, grid_segments
from hypothesis import given
from hypothesis import strategies as st

from starboard.geo.snapping import (
    ReviewItem,
    ReviewReason,
    SnappedStop,
    Snapper,
    StopPoint,
    snap_stops,
)
from starboard.geo.state_graph import build_state_graph
from starboard.solver.graph import CurbSide, Direction, LonLat, StreetSegment

GRAPH = build_state_graph(grid_segments())
SNAPPER = Snapper(GRAPH)


def point_beside(segment_id: str, fraction: float, offset_m: float) -> LonLat:
    """A point `fraction` along a segment, `offset_m` to the left of its forward direction."""
    segment = GRAPH.segments[segment_id]
    (x0, y0), (x1, y1) = (PROJECTION.to_xy(p) for p in segment.geometry)
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    x, y = x0 + ux * length * fraction, y0 + uy * length * fraction
    return at(x - uy * offset_m, y + ux * offset_m)


def is_on_right_of_required_pass(location: LonLat, snapped: SnappedStop) -> bool:
    segment = GRAPH.segments[snapped.segment_id]
    (x0, y0), (x1, y1) = (PROJECTION.to_xy(p) for p in segment.geometry)
    if snapped.required_pass.direction is Direction.REVERSE:
        (x0, y0), (x1, y1) = (x1, y1), (x0, y0)
    px, py = PROJECTION.to_xy(location)
    return (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0) < 0


@given(
    segment_id=st.sampled_from(sorted(GRAPH.segments)),
    fraction=st.floats(0.3, 0.7),
    offset=st.floats(3.0, 24.0),
    left=st.booleans(),
)
def test_a_stop_beside_a_street_is_serviced_from_the_right(segment_id, fraction, offset, left):
    location = point_beside(segment_id, fraction, offset if left else -offset)
    result = SNAPPER.snap(StopPoint("s", location))
    segment = GRAPH.segments[segment_id]
    legal = segment.reverse_allowed if left else segment.forward_allowed

    if not legal:
        assert isinstance(result, ReviewItem)
        assert result.reason is ReviewReason.WRONG_SIDE_OF_ONE_WAY
        return
    assert isinstance(result, SnappedStop)
    assert result.segment_id == segment_id
    assert result.side_of_forward is (CurbSide.LEFT if left else CurbSide.RIGHT)
    assert result.distance_from_centerline_m == pytest.approx(offset, abs=0.01)
    assert result.distance_along_m == pytest.approx(BLOCK_M * fraction, abs=0.01)
    assert is_on_right_of_required_pass(location, result)


def test_a_stop_far_from_every_street_goes_to_review():
    result = SNAPPER.snap(StopPoint("far", at(-500.0, -500.0)))
    assert isinstance(result, ReviewItem)
    assert result.reason is ReviewReason.OUTSIDE_NETWORK


def test_a_stop_on_the_centerline_goes_to_review():
    result = SNAPPER.snap(StopPoint("mid", point_beside("h-0-1", 0.5, 0.0)))
    assert isinstance(result, ReviewItem)
    assert result.reason is ReviewReason.SIDE_UNDETERMINED


def test_a_stop_between_two_parallel_streets_goes_to_review():
    result = SNAPPER.snap(StopPoint("between", at(1.5 * BLOCK_M, 0.5 * BLOCK_M + 1.0)))
    assert isinstance(result, ReviewItem)
    assert result.reason is ReviewReason.AMBIGUOUS_STREET
    assert {"h-0-1", "h-1-1"} <= set(result.candidate_segment_ids)


def test_a_corner_lot_goes_to_review():
    result = SNAPPER.snap(StopPoint("corner", at(BLOCK_M + 10.0, BLOCK_M + 10.0)))
    assert isinstance(result, ReviewItem)
    assert result.reason is ReviewReason.AMBIGUOUS_STREET


def test_snap_stops_splits_snapped_from_review_without_raising():
    outcome = snap_stops(
        GRAPH,
        [
            StopPoint("ok", point_beside("h-0-1", 0.5, -10.0)),
            StopPoint("far", at(-500.0, -500.0)),
        ],
    )
    assert [s.stop_id for s in outcome.snapped] == ["ok"]
    assert [r.stop_id for r in outcome.review] == ["far"]


def test_a_corner_lot_takes_the_street_its_address_names():
    location = at(BLOCK_M + 10.0, 10.0)  # inside the corner of row 0 and column 1
    by_row = SNAPPER.snap(StopPoint("corner", location, street="Row 0 St"))
    by_column = SNAPPER.snap(StopPoint("corner", location, street="column 1 ave."))
    assert isinstance(by_row, SnappedStop)
    assert by_row.segment_id == "h-0-1"
    assert isinstance(by_column, SnappedStop)
    assert by_column.segment_id == "v-0-1"


def test_an_address_naming_neither_street_keeps_the_corner_in_review():
    result = SNAPPER.snap(StopPoint("corner", at(BLOCK_M + 10.0, BLOCK_M + 10.0), street="Elm St"))
    assert isinstance(result, ReviewItem)
    assert result.reason is ReviewReason.AMBIGUOUS_STREET


def test_unserviceable_segments_are_never_snapped_to():
    motorway = StreetSegment(
        segment_id="motorway",
        from_node=900,
        to_node=901,
        geometry=(at(-50.0, 50.0), at(-50.0, 250.0)),
        length_m=200.0,
        name="Interstate 95",
        forward_allowed=True,
        reverse_allowed=False,
        road_class="motorway",
        serviceable=False,
    )
    snapper = Snapper(build_state_graph([*grid_segments(), motorway]))
    result = snapper.snap(StopPoint("beside", at(-45.0, 150.0)))  # 5 m from it, 45 m from column 0
    assert isinstance(result, SnappedStop)
    assert result.segment_id.startswith("v-")


def test_a_planner_placement_takes_the_chosen_street_and_side():
    # A stop as near one street as another; the planner says which, and which curb.
    stop = StopPoint("p", at(BLOCK_M / 2, BLOCK_M / 2))
    placed = SNAPPER.place(stop, "h-0-0", CurbSide.LEFT)
    assert placed.segment_id == "h-0-0"
    assert placed.side_of_forward is CurbSide.LEFT
    assert placed.required_pass.direction is Direction.REVERSE
    assert placed.distance_along_m == pytest.approx(BLOCK_M / 2, abs=0.5)


def test_a_placement_on_an_unknown_street_is_refused():
    with pytest.raises(KeyError):
        SNAPPER.place(StopPoint("p", at(10, 10)), "no-such-street", CurbSide.RIGHT)
