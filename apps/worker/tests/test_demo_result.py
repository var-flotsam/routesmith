"""The demo result: built as the worker builds a run's result, and saved for the static demo."""

import csv
import hashlib
import json
from datetime import UTC, datetime

import pytest

from starboard.geo.osm import fetch_network
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.worker.demo_result import (
    ABOUT_FILE,
    RESULT_DIR,
    ROUTE_FILE,
    SHARED_RUN_FILE,
    STOPS_FILE,
    build,
    keeping_built_time,
    read,
    write,
)

GRID = Grid()
BUILT_AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
DEMO_DIR = RESULT_DIR.parent
REPO_ROOT = DEMO_DIR.parents[1]
EXTRACT = REPO_ROOT / "cache" / "osm" / "extracts" / "connecticut-latest.osm.pbf"

# Four stops beside streets, then one in the middle of a block, which goes to review.
POINTS = [(20, -10), (60, -10), (110, 50), (150, 90), (50, 50)]


def _stops_csv(routes: list[str] | None = None, points=POINTS) -> bytes:
    rows = ["stop_id,current_sequence,lon,lat" + (",route_id" if routes else "")]
    for index, (x, y) in enumerate(points, 1):
        p = GRID.at(x, y)
        rows.append(
            f"s{index},{index},{p.lon},{p.lat}" + (f",{routes[index - 1]}" if routes else "")
        )
    return ("\n".join(rows) + "\n").encode("utf-8")


def _route_json() -> bytes:
    corner = GRID.at(0, 0)
    site = {"lon": corner.lon, "lat": corner.lat}
    return json.dumps({"yard": site, "disposal": site, "capacity_carts": 10}).encode("utf-8")


def _grid(bbox):
    return build_state_graph(GRID.segments())


def _build(stops_csv=None, network=_grid, at=BUILT_AT):
    return build(stops_csv or _stops_csv(), _route_json(), network, clock=lambda: at)


def test_the_demo_result_is_a_shared_run_of_the_snapped_stops():
    result = _build()
    report = result.shared.report
    assert result.shared.finished_at == BUILT_AT
    assert result.about.stops_in_file == 5
    assert result.about.stops_placed == 4
    assert sum(result.about.stops_in_review.values()) == 1
    assert result.about.input_sha256 == {
        STOPS_FILE: hashlib.sha256(_stops_csv()).hexdigest(),
        ROUTE_FILE: hashlib.sha256(_route_json()).hexdigest(),
    }
    served = {stop for route in report.optimized.routes for stop in route.order}
    assert served | {u.stop_id for u in report.unserved} == {"s1", "s2", "s3", "s4"}
    assert report.optimized.area.wrong_side_pickups == 0
    assert all(route.path for route in [*report.current.routes, *report.optimized.routes])


def test_a_stop_whose_street_the_solve_network_lacks_is_unserved():
    calls = []

    def network(bbox):
        # The second network, around the snapped stops only, has lost s4's street.
        calls.append(bbox)
        segments = GRID.segments()
        if len(calls) > 1:
            segments = [s for s in segments if s.segment_id != "h-1-1"]
        return build_state_graph(segments)

    report = _build(network=network).shared.report
    assert [(u.stop_id, u.reason) for u in report.unserved] == [("s4", "street_not_in_network")]
    assert "s4" not in {stop for route in report.optimized.routes for stop in route.order}


def test_a_file_with_current_routes_gets_a_truck_per_route():
    report = _build(_stops_csv(routes=["a", "a", "b", "b", "b"])).shared.report
    assert report.trucks == 2
    assert len(report.current.routes) == len(report.optimized.routes) == 2


def test_a_stop_file_the_importer_would_reject_or_could_not_snap_is_refused():
    with pytest.raises(ValueError, match="line 3"):
        _build(_stops_csv().replace(b"s2,2,", b"s2,2,999"))
    with pytest.raises(ValueError, match="no snapped stops"):
        _build(_stops_csv(points=[(50, 50)]))


def test_the_same_stops_and_network_write_the_same_files(tmp_path):
    write(_build(), tmp_path / "first")
    write(_build(), tmp_path / "second")
    for name in (SHARED_RUN_FILE, ABOUT_FILE):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_the_written_files_read_back_as_the_api_shapes(tmp_path):
    result = _build()
    write(result, tmp_path)
    assert read(tmp_path) == result


def test_an_unchanged_rebuild_keeps_the_time_the_result_was_built():
    first = _build()
    later = datetime(2026, 11, 2, tzinfo=UTC)
    assert keeping_built_time(_build(at=later), first) == first
    changed = _build(_stops_csv(points=POINTS[:3]), at=later)
    assert keeping_built_time(changed, first).shared.finished_at == later


def test_the_committed_demo_result_is_for_the_committed_demo_files():
    committed = read(RESULT_DIR)
    about, report = committed.about, committed.shared.report
    assert about.input_sha256 == {
        name: hashlib.sha256((DEMO_DIR / name).read_bytes()).hexdigest()
        for name in (STOPS_FILE, ROUTE_FILE)
    }, "data/demo changed: rebuild the result (see data/demo/PROVENANCE.md)"
    with (DEMO_DIR / STOPS_FILE).open(encoding="utf-8", newline="") as handle:
        stop_ids = {row["stop_id"] for row in csv.DictReader(handle)}
    assert about.stops_in_file == len(stop_ids)
    assert about.stops_placed + sum(about.stops_in_review.values()) == about.stops_in_file
    served = [stop for route in report.optimized.routes for stop in route.order]
    placed = {*served, *(u.stop_id for u in report.unserved)}
    assert len(placed) == about.stops_placed and placed <= stop_ids
    assert about.osm_snapshot == report.osm_snapshot is not None
    # What the demo is for: the optimized route is quicker, and it never picks up a cart
    # from the wrong side.
    assert report.optimized.area.route_time_s < report.current.area.route_time_s
    assert report.optimized.area.wrong_side_pickups == 0


def test_the_committed_result_is_written_as_the_builder_writes_it(tmp_path):
    write(read(RESULT_DIR), tmp_path)
    for name in (SHARED_RUN_FILE, ABOUT_FILE):
        assert (tmp_path / name).read_bytes() == (RESULT_DIR / name).read_bytes(), name


@pytest.mark.demo
def test_rebuilding_the_demo_result_gives_the_committed_one():
    committed = read(RESULT_DIR)
    extract = EXTRACT if EXTRACT.exists() else None

    def network(bbox):
        return fetch_network(bbox, cache_dir=REPO_ROOT / "cache" / "osm", extract=extract)

    rebuilt = build(
        (DEMO_DIR / STOPS_FILE).read_bytes(),
        (DEMO_DIR / ROUTE_FILE).read_bytes(),
        network,
        clock=lambda: datetime.now(UTC),
    )
    if rebuilt.about.osm_snapshot != committed.about.osm_snapshot:
        pytest.skip("the cached OSM network is from another snapshot than the committed result")
    assert keeping_built_time(rebuilt, committed) == committed
