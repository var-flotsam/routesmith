"""A synthetic street grid for tests: 4x4 intersections, 100 m blocks.

Rows run west to east and are numbered from the south; columns run south to
north. Row 1 is one-way eastbound, row 2 one-way westbound; every other
street is two-way. Each segment is its own OSM way, as at intersections in
real OSM data: way `way_id(segment_id)`.
"""

from starboard.geo.projection import LocalProjection
from starboard.solver.graph import LonLat, StreetSegment

SIZE = 4
BLOCK_M = 100.0
ORIGIN = LonLat(lon=-73.0, lat=41.0)
PROJECTION = LocalProjection(ORIGIN)


def node(row: int, col: int) -> int:
    return row * SIZE + col


def way_id(segment_id: str) -> int:
    kind, row, col = segment_id.split("-")
    return (1000 if kind == "h" else 2000) + int(row) * 10 + int(col)


def at(x: float, y: float) -> LonLat:
    return PROJECTION.to_lonlat(x, y)


def grid_segments() -> list[StreetSegment]:
    segments: list[StreetSegment] = []
    for row in range(SIZE):
        for col in range(SIZE - 1):
            segments.append(
                StreetSegment(
                    segment_id=f"h-{row}-{col}",
                    from_node=node(row, col),
                    to_node=node(row, col + 1),
                    geometry=(
                        at(col * BLOCK_M, row * BLOCK_M),
                        at((col + 1) * BLOCK_M, row * BLOCK_M),
                    ),
                    length_m=BLOCK_M,
                    name=f"Row {row} Street",
                    forward_allowed=row != 2,
                    reverse_allowed=row != 1,
                    osm_way_ids=(way_id(f"h-{row}-{col}"),),
                )
            )
    for col in range(SIZE):
        for row in range(SIZE - 1):
            segments.append(
                StreetSegment(
                    segment_id=f"v-{row}-{col}",
                    from_node=node(row, col),
                    to_node=node(row + 1, col),
                    geometry=(
                        at(col * BLOCK_M, row * BLOCK_M),
                        at(col * BLOCK_M, (row + 1) * BLOCK_M),
                    ),
                    length_m=BLOCK_M,
                    name=f"Column {col} Avenue",
                    forward_allowed=True,
                    reverse_allowed=True,
                    osm_way_ids=(way_id(f"v-{row}-{col}"),),
                )
            )
    return segments
