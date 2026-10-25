"""Put the yard and disposal site on the street network.

A site is off-street; the truck enters and leaves it at the nearest
intersection or street end, which becomes the site's `Place` node.
"""

import math

from starboard.geo.projection import LocalProjection
from starboard.solver import defaults
from starboard.solver.graph import LonLat, Place, StateGraph


def place_at(graph: StateGraph, name: str, location: LonLat) -> Place:
    """The network node nearest `location`, as a place called `name`.

    Raises ValueError if no node is within `defaults.SITE_MAX_DISTANCE`, which
    means the location is outside the street network that was fetched.
    """
    projection = LocalProjection.centred_on(p for s in graph.segments.values() for p in s.geometry)
    target = projection.to_xy(location)
    best: tuple[float, int] | None = None
    for segment in graph.segments.values():
        for node, point in (
            (segment.from_node, segment.geometry[0]),
            (segment.to_node, segment.geometry[-1]),
        ):
            distance = math.dist(projection.to_xy(point), target)
            if best is None or (distance, node) < best:
                best = (distance, node)
    if best is None or best[0] > defaults.SITE_MAX_DISTANCE.value:
        raise ValueError(f"{name} is not within {defaults.SITE_MAX_DISTANCE.value:g} m of a street")
    return Place(name, best[1])
