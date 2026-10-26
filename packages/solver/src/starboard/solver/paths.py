"""A driven route as a line on the map: the points the truck passes, in driving order.

Each traversal contributes the stretch of its segment between `start_m` and `end_m`,
in the direction driven; a stretch that starts where the last one ended does not
repeat the shared point. Distances along a segment are measured on a local flat
approximation of the earth, scaled to the segment's own length, which is ample for
drawing a street-scale line.
"""

import itertools
import math
from collections.abc import Sequence

from starboard.solver.graph import Direction, LonLat, StateGraph
from starboard.solver.route import DrivenRoute

Point = tuple[float, float]  # (lon, lat)

_EARTH_RADIUS_M = 6_371_008.8  # IUGG mean radius, https://en.wikipedia.org/wiki/Earth_radius
# Points closer than this are the same point on a drawn line.
_SAME_POINT_DEGREES = 1e-9


def _flat_distances(points: Sequence[LonLat]) -> list[float]:
    """Cumulative distance along `points` in metres, on an equirectangular projection."""
    cumulative = [0.0]
    for a, b in itertools.pairwise(points):
        mean_lat = math.radians((a.lat + b.lat) / 2)
        dx = math.radians(b.lon - a.lon) * math.cos(mean_lat)
        dy = math.radians(b.lat - a.lat)
        cumulative.append(cumulative[-1] + _EARTH_RADIUS_M * math.hypot(dx, dy))
    return cumulative


def _at(points: Sequence[LonLat], cumulative: Sequence[float], distance: float) -> Point:
    for k in range(1, len(points)):
        if distance <= cumulative[k] or k == len(points) - 1:
            span = cumulative[k] - cumulative[k - 1]
            t = 0.0 if span == 0 else min(max((distance - cumulative[k - 1]) / span, 0.0), 1.0)
            a, b = points[k - 1], points[k]
            return (a.lon + t * (b.lon - a.lon), a.lat + t * (b.lat - a.lat))
    return (points[0].lon, points[0].lat)


def stretch(
    geometry: Sequence[LonLat], length_m: float, start_m: float, end_m: float
) -> list[Point]:
    """The part of `geometry` from `start_m` to `end_m` along it, both in the segment's own
    metres (`length_m` long), including the bends between."""
    cumulative = _flat_distances(geometry)
    scale = cumulative[-1] / length_m if length_m > 0 else 0.0
    lo, hi = start_m * scale, end_m * scale
    inside = [(p.lon, p.lat) for p, d in zip(geometry, cumulative, strict=True) if lo < d < hi]
    return [_at(geometry, cumulative, lo), *inside, _at(geometry, cumulative, hi)]


def driven_path(graph: StateGraph, route: DrivenRoute) -> list[Point]:
    """Every point the route drives through, from its first pass to its last."""
    path: list[Point] = []
    for traversal in route.traversals:
        segment = graph.segments[traversal.on_pass.segment_id]
        geometry = list(segment.geometry)
        if traversal.on_pass.direction is Direction.REVERSE:
            geometry.reverse()
        for point in stretch(geometry, segment.length_m, traversal.start_m, traversal.end_m):
            last = path[-1] if path else None
            same = last is not None and (
                abs(last[0] - point[0]) < _SAME_POINT_DEGREES
                and abs(last[1] - point[1]) < _SAME_POINT_DEGREES
            )
            if not same:
                path.append(point)
    return path
