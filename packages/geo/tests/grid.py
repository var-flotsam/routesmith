"""The default synthetic grid used across the geo tests: 4x4 intersections,
100 m blocks, row 1 one-way eastbound and row 2 one-way westbound."""

from starboard.geo.synthetic import Grid
from starboard.solver.graph import LonLat, StreetSegment

GRID = Grid()
SIZE = GRID.size
BLOCK_M = GRID.block_m
PROJECTION = GRID.projection
way_id = Grid.way_id


def node(row: int, col: int) -> int:
    return GRID.node(row, col)


def at(x: float, y: float) -> LonLat:
    return GRID.at(x, y)


def grid_segments() -> list[StreetSegment]:
    return GRID.segments()
