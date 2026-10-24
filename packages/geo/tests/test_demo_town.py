"""The geo pipeline on the demo town: Byram, Greenwich, CT.

Needs the OSM network for the demo area, fetched from Overpass on the first
run and read from `cache/osm/` after that. Run with `pytest -m demo`.
"""

import csv
import itertools
import math
from collections import Counter
from pathlib import Path

import pytest

from starboard.geo.osm import bbox_around, fetch_network
from starboard.geo.projection import LocalProjection
from starboard.geo.snapping import SnappedStop, Snapper, StopPoint
from starboard.solver.graph import Direction, LonLat

pytestmark = pytest.mark.demo

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_STOPS = REPO_ROOT / "data" / "demo" / "stops.csv"
NETWORK_MARGIN_M = 300.0  # room for the streets that bound the outermost stops


@pytest.fixture(scope="module")
def stops() -> list[StopPoint]:
    with DEMO_STOPS.open(encoding="utf-8") as handle:
        return [
            StopPoint(
                row["stop_id"],
                LonLat(lon=float(row["lon"]), lat=float(row["lat"])),
                street=row["street"],
            )
            for row in csv.DictReader(handle)
        ]


@pytest.fixture(scope="module")
def graph(stops):
    bbox = bbox_around((s.location for s in stops), NETWORK_MARGIN_M)
    return fetch_network(bbox, cache_dir=REPO_ROOT / "cache" / "osm")


def test_network_records_its_osm_snapshot(graph):
    assert graph.osm_snapshot


def test_one_way_streets_have_a_single_pass(graph):
    passes_per_segment = Counter(p.segment_id for p in graph.passes)
    for segment_id, segment in graph.segments.items():
        assert passes_per_segment[segment_id] == (1 if segment.is_one_way else 2)


def test_most_demo_stops_snap_and_each_is_on_the_right_of_its_pass(graph, stops):
    snapper = Snapper(graph)
    projection = LocalProjection.centred_on(p for s in graph.segments.values() for p in s.geometry)
    results = {stop.stop_id: snapper.snap(stop) for stop in stops}
    snapped = [r for r in results.values() if isinstance(r, SnappedStop)]
    review_reasons = Counter(r.reason for r in results.values() if not isinstance(r, SnappedStop))

    assert len(snapped) >= 0.9 * len(stops), review_reasons

    by_id = {s.stop_id: s for s in stops}
    for result in snapped:
        assert result.required_pass in graph.passes
        x0, y0, x1, y1 = piece_at(graph.segments[result.segment_id], result, projection)
        px, py = projection.to_xy(by_id[result.stop_id].location)
        assert (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0) < 0, result.stop_id


def piece_at(segment, result: SnappedStop, projection: LocalProjection):
    """The straight piece of the segment, in the required pass's direction, at the snap point."""
    xy = [projection.to_xy(p) for p in segment.geometry]
    pieces = list(itertools.pairwise(xy))
    lengths = [math.dist(a, b) for a, b in pieces]
    along = result.distance_along_m
    if result.required_pass.direction is Direction.REVERSE:
        pieces = [(b, a) for a, b in reversed(pieces)]
        lengths.reverse()
        along = sum(lengths) - along
    travelled = 0.0
    index = 0
    for index, length in enumerate(lengths):  # noqa: B007 - the loop finds `index`
        if travelled + length >= along:
            break
        travelled += length
    start, end = pieces[index]
    return (*start, *end)
