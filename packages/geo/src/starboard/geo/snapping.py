"""Snap stop points to street segments and decide which pass services each one.

A stop's curb side comes from the sign of the cross product between the
segment's direction at the snap point and the vector to the stop. The pass
that services it is the direction that puts the stop on the truck's right.
When a point is about equally close to two streets (typically a corner lot),
the street named in the stop's address decides. Anything that cannot be
decided becomes a review item with a reason; this module never raises on
stop data.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from shapely import LineString, Point, STRtree

from starboard.geo.projection import LocalProjection
from starboard.solver import defaults
from starboard.solver.graph import (
    CurbSide,
    Direction,
    LonLat,
    Pass,
    SnappedStop,
    StateGraph,
    StreetSegment,
)
from starboard.solver.street_names import same_street_name

# Half-length of the stretch of line used to read its direction at the snap point.
_TANGENT_HALF_LENGTH_M = 0.5


@dataclass(frozen=True, slots=True)
class StopPoint:
    """A stop's location, and the street its address names when there is one."""

    stop_id: str
    location: LonLat
    street: str | None = None


class ReviewReason(StrEnum):
    OUTSIDE_NETWORK = "outside_network"
    AMBIGUOUS_STREET = "ambiguous_street"
    SIDE_UNDETERMINED = "side_undetermined"
    WRONG_SIDE_OF_ONE_WAY = "wrong_side_of_one_way"
    ADDRESS_NOT_FOUND = "address_not_found"
    ADDRESS_AMBIGUOUS = "address_ambiguous"
    ADDRESS_INEXACT = "address_inexact"  # placed after the geocoder changed the address


@dataclass(frozen=True, slots=True)
class ReviewItem:
    stop_id: str
    reason: ReviewReason
    detail: str
    candidate_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapOutcome:
    snapped: tuple[SnappedStop, ...]
    review: tuple[ReviewItem, ...]


def _side_of(line: LineString, along: float, point: Point) -> tuple[CurbSide | None, float]:
    """Which side of the line's direction the point is on, and its distance from the line."""
    distance = line.distance(point)
    if distance < defaults.CURB_SIDE_MIN_OFFSET.value:
        return None, distance
    a = line.interpolate(max(along - _TANGENT_HALF_LENGTH_M, 0.0))
    b = line.interpolate(min(along + _TANGENT_HALF_LENGTH_M, line.length))
    cross = (b.x - a.x) * (point.y - a.y) - (b.y - a.y) * (point.x - a.x)
    return (CurbSide.LEFT if cross > 0 else CurbSide.RIGHT), distance


class Snapper:
    """Snaps points to one network; build once, then snap any number of stops.

    Only serviceable segments are candidates, so a stop beside a motorway
    snaps to the street it is actually on.
    """

    def __init__(self, graph: StateGraph) -> None:
        everything = list(graph.segments.values())
        self._projection = LocalProjection.centred_on(p for s in everything for p in s.geometry)
        self._segments: Sequence[StreetSegment] = [s for s in everything if s.serviceable]
        self._lines = [
            LineString([self._projection.to_xy(p) for p in s.geometry]) for s in self._segments
        ]
        self._tree = STRtree(self._lines)
        self._index_of = {s.segment_id: k for k, s in enumerate(self._segments)}

    def snap(self, stop: StopPoint) -> SnappedStop | ReviewItem:
        max_distance = defaults.SNAP_MAX_DISTANCE.value
        point = Point(self._projection.to_xy(stop.location))
        candidates = sorted(
            (
                (self._lines[i].distance(point), self._segments[i].segment_id, int(i))
                for i in self._tree.query(point.buffer(max_distance))
            ),
        )
        candidates = [c for c in candidates if c[0] <= max_distance]
        if not candidates:
            return ReviewItem(
                stop.stop_id,
                ReviewReason.OUTSIDE_NETWORK,
                f"no street within {max_distance:g} m",
            )

        nearest_distance = candidates[0][0]
        close = [
            i
            for distance, _, i in candidates
            if distance - nearest_distance < defaults.SNAP_AMBIGUITY_MARGIN.value
        ]
        nearest = self._segments[close[0]]
        if any(not same_street_name(nearest.name, self._segments[i].name) for i in close[1:]):
            named = [i for i in close if same_street_name(stop.street, self._segments[i].name)]
            if not named:
                return ReviewItem(
                    stop.stop_id,
                    ReviewReason.AMBIGUOUS_STREET,
                    "about equally close to more than one street",
                    tuple(self._segments[i].segment_id for i in close),
                )
            close = named
        best_index = close[0]
        best = self._segments[best_index]
        best_id = best.segment_id

        line = self._lines[best_index]
        along = line.project(point)
        side, distance = _side_of(line, along, point)
        if side is None:
            return ReviewItem(
                stop.stop_id,
                ReviewReason.SIDE_UNDETERMINED,
                f"{distance:.1f} m from the centerline; side of street unclear",
                (best_id,),
            )

        direction = Direction.FORWARD if side is CurbSide.RIGHT else Direction.REVERSE
        allowed = best.forward_allowed if direction is Direction.FORWARD else best.reverse_allowed
        if not allowed:
            return ReviewItem(
                stop.stop_id,
                ReviewReason.WRONG_SIDE_OF_ONE_WAY,
                "on the left of a one-way street; a right-side arm cannot reach it",
                (best_id,),
            )

        return SnappedStop(
            stop_id=stop.stop_id,
            segment_id=best_id,
            distance_along_m=along,
            distance_from_centerline_m=distance,
            side_of_forward=side,
            required_pass=Pass(best_id, direction),
            street=stop.street,
        )

    def place(self, stop: StopPoint, segment_id: str, side: CurbSide) -> SnappedStop:
        """The stop on the street and curb a planner chose; KeyError for an unknown street.

        The planner's word settles the street and the side; the point only sets how
        far along the street the cart stands.
        """
        index = self._index_of[segment_id]
        line = self._lines[index]
        point = Point(self._projection.to_xy(stop.location))
        direction = Direction.FORWARD if side is CurbSide.RIGHT else Direction.REVERSE
        return SnappedStop(
            stop_id=stop.stop_id,
            segment_id=segment_id,
            distance_along_m=line.project(point),
            distance_from_centerline_m=line.distance(point),
            side_of_forward=side,
            required_pass=Pass(segment_id, direction),
            street=stop.street,
        )


def snap_stops(graph: StateGraph, stops: Iterable[StopPoint]) -> SnapOutcome:
    snapper = Snapper(graph)
    snapped: list[SnappedStop] = []
    review: list[ReviewItem] = []
    for stop in stops:
        result = snapper.snap(stop)
        if isinstance(result, SnappedStop):
            snapped.append(result)
        else:
            review.append(result)
    return SnapOutcome(tuple(snapped), tuple(review))
