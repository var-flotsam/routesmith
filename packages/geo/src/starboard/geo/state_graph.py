"""Build the (segment, direction) state graph from street segments."""

from collections import defaultdict
from collections.abc import Iterable

from starboard.geo.projection import LocalProjection, heading_change_deg, heading_deg
from starboard.solver.graph import Direction, Pass, StateGraph, StreetSegment, Transition


def _pass_nodes(segment: StreetSegment, direction: Direction) -> tuple[int, int]:
    if direction is Direction.FORWARD:
        return segment.from_node, segment.to_node
    return segment.to_node, segment.from_node


def _pass_headings(
    segment: StreetSegment, direction: Direction, projection: LocalProjection
) -> tuple[float, float]:
    """Heading on entering and on leaving the segment in the given direction."""
    xy = [projection.to_xy(point) for point in segment.geometry]
    if direction is Direction.REVERSE:
        xy.reverse()
    (x0, y0), (x1, y1) = xy[0], xy[1]
    (xa, ya), (xb, yb) = xy[-2], xy[-1]
    return heading_deg(x1 - x0, y1 - y0), heading_deg(xb - xa, yb - ya)


def build_state_graph(
    segments: Iterable[StreetSegment], osm_snapshot: str | None = None
) -> StateGraph:
    """Every legal pass, and every transition between passes that meet at a node.

    Transitions are not filtered by turn rules here: U-turns are flagged, and
    the solver decides which are allowed (dead ends always are).
    """
    ordered = sorted(segments, key=lambda segment: segment.segment_id)
    by_id = {segment.segment_id: segment for segment in ordered}
    if not by_id:
        raise ValueError("cannot build a state graph from no segments")
    for segment in by_id.values():
        if len(segment.geometry) < 2:
            raise ValueError(f"segment {segment.segment_id} has fewer than two points")
        if not (segment.forward_allowed or segment.reverse_allowed):
            raise ValueError(f"segment {segment.segment_id} allows no direction of travel")

    projection = LocalProjection.centred_on(p for s in by_id.values() for p in s.geometry)

    passes: list[Pass] = []
    entry_heading: dict[Pass, float] = {}
    exit_heading: dict[Pass, float] = {}
    starting_at: dict[int, list[Pass]] = defaultdict(list)
    ending_at: dict[Pass, int] = {}
    endpoint_count: dict[int, int] = defaultdict(int)

    for segment in by_id.values():
        endpoint_count[segment.from_node] += 1
        endpoint_count[segment.to_node] += 1
        for direction, allowed in (
            (Direction.FORWARD, segment.forward_allowed),
            (Direction.REVERSE, segment.reverse_allowed),
        ):
            if not allowed:
                continue
            state = Pass(segment.segment_id, direction)
            start, end = _pass_nodes(segment, direction)
            entry_heading[state], exit_heading[state] = _pass_headings(
                segment, direction, projection
            )
            passes.append(state)
            starting_at[start].append(state)
            ending_at[state] = end

    transitions = [
        Transition(
            from_pass=arriving,
            to_pass=leaving,
            via_node=node,
            heading_change_deg=heading_change_deg(exit_heading[arriving], entry_heading[leaving]),
            is_u_turn=(
                leaving.segment_id == arriving.segment_id
                and leaving.direction is not arriving.direction
            ),
        )
        for arriving in passes
        for node in (ending_at[arriving],)
        for leaving in starting_at[node]
    ]

    return StateGraph(
        segments=by_id,
        passes=tuple(passes),
        transitions=tuple(transitions),
        dead_end_nodes=frozenset(node for node, count in endpoint_count.items() if count == 1),
        osm_snapshot=osm_snapshot,
    )
