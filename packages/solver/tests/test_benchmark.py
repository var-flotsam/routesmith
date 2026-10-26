"""Scale benchmark: 1,000 to 10,000 stops on synthetic grids (ADR-0003, delivery step 7).

Run with `uv run pytest packages/solver -m benchmark -s`; it is kept out of the
merge gate because the largest case takes minutes. Each case prints its wall
time, total route time and gap, and `solve_routes` checks every hard constraint.
Each truck gets 1,000 stops, the most one truck serves in a day.
"""

import math
import time

import pytest

from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.fleet import Area, FleetSettings, solve_routes
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites, TruckProfile

CARTS_PER_CURB = 3  # 25 m lots on a 100 m block, clear of the corners
CAPACITY = 420  # the demo truck's carts per load


def _area(stops: int) -> Area:
    # Each block has two curbs on each of its streets; size the grid to hold the stops.
    size = math.ceil(math.sqrt(stops / (4 * CARTS_PER_CURB))) + 1
    grid = Grid(size=size, one_way_east=frozenset({1}), one_way_west=frozenset({size - 2}))
    graph = build_state_graph(grid.segments())
    snapper = Snapper(graph)
    snapped: list[SnappedStop] = []
    for segment in grid.segments():
        (x0, y0), (x1, y1) = (grid.projection.to_xy(p) for p in segment.geometry)
        ux, uy = (x1 - x0) / grid.block_m, (y1 - y0) / grid.block_m
        for side in (1.0, -1.0):
            for k in range(CARTS_PER_CURB):
                if len(snapped) >= stops:
                    break
                along = grid.block_m * (k + 1) / (CARTS_PER_CURB + 1)
                off = 8.0 * side
                point = grid.projection.to_lonlat(
                    x0 + ux * along - uy * off, y0 + uy * along + ux * off
                )
                result = snapper.snap(StopPoint(f"b{len(snapped)}", point))
                if isinstance(result, SnappedStop):
                    snapped.append(result)
    yard = Place("yard", 0)
    return Area(graph, tuple(snapped), RouteSites(yard, Place("disposal", 0)))


@pytest.mark.benchmark
@pytest.mark.parametrize(("stops", "trucks"), [(1_000, 1), (3_000, 3), (10_000, 10)])
def test_scale(stops, trucks):
    area = _area(stops)
    settings = SolveSettings(TruckProfile(capacity_carts=CAPACITY))
    started = time.perf_counter()
    result = solve_routes(area, FleetSettings(trucks, solve=settings))
    elapsed = time.perf_counter() - started
    served = sum(len(r.route.pickups) for r in result.routes)
    print(
        f"\n{len(area.stops)} stops, {trucks} trucks: {elapsed:,.0f} s wall, "
        f"total {result.total_ms / 1000:,.0f} s, longest {result.longest_ms / 1000:,.0f} s, "
        f"gap {result.gap:.1%}, served {served}, balance met {result.balance_met}"
    )
    assert served + len(result.unserved) == len(area.stops)
