"""Synthetic street grids, for tests and property tests.

A grid has `size` x `size` intersections `block_m` apart. Rows run west to
east and are numbered from the south; columns run south to north. Rows named
in `one_way_east` or `one_way_west` are one-way in that direction; every
other street is two-way. Each segment is its own OSM way, as at
intersections in real OSM data.
"""

from collections.abc import Collection
from dataclasses import dataclass, field

from starboard.geo.projection import LocalProjection
from starboard.solver.graph import LonLat, StreetSegment

DEFAULT_ORIGIN = LonLat(lon=-73.0, lat=41.0)


@dataclass(frozen=True, slots=True)
class Grid:
    size: int = 4
    block_m: float = 100.0
    origin: LonLat = DEFAULT_ORIGIN
    one_way_east: Collection[int] = field(default_factory=lambda: frozenset({1}))
    one_way_west: Collection[int] = field(default_factory=lambda: frozenset({2}))

    @property
    def projection(self) -> LocalProjection:
        return LocalProjection(self.origin)

    def node(self, row: int, col: int) -> int:
        return row * self.size + col

    def at(self, x: float, y: float) -> LonLat:
        """The point `x` metres east and `y` metres north of the south-west corner."""
        return self.projection.to_lonlat(x, y)

    @staticmethod
    def way_id(segment_id: str) -> int:
        kind, row, col = segment_id.split("-")
        return (1000 if kind == "h" else 2000) + int(row) * 100 + int(col)

    def segments(self) -> list[StreetSegment]:
        """`h-<row>-<col>` runs east from (row, col); `v-<row>-<col>` runs north from it."""
        size, block = self.size, self.block_m
        segments: list[StreetSegment] = []
        for row in range(size):
            for col in range(size - 1):
                segment_id = f"h-{row}-{col}"
                segments.append(
                    StreetSegment(
                        segment_id=segment_id,
                        from_node=self.node(row, col),
                        to_node=self.node(row, col + 1),
                        geometry=(
                            self.at(col * block, row * block),
                            self.at((col + 1) * block, row * block),
                        ),
                        length_m=block,
                        name=f"Row {row} Street",
                        forward_allowed=row not in self.one_way_west,
                        reverse_allowed=row not in self.one_way_east,
                        road_class="residential",
                        osm_way_ids=(self.way_id(segment_id),),
                    )
                )
        for col in range(size):
            for row in range(size - 1):
                segment_id = f"v-{row}-{col}"
                segments.append(
                    StreetSegment(
                        segment_id=segment_id,
                        from_node=self.node(row, col),
                        to_node=self.node(row + 1, col),
                        geometry=(
                            self.at(col * block, row * block),
                            self.at(col * block, (row + 1) * block),
                        ),
                        length_m=block,
                        name=f"Column {col} Avenue",
                        forward_allowed=True,
                        reverse_allowed=True,
                        road_class="residential",
                        osm_way_ids=(self.way_id(segment_id),),
                    )
                )
        return segments
