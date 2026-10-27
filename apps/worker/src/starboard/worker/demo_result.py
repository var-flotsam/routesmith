"""The demo route's result, saved as files for the static demo (ADR-0007).

The static demo shows one precomputed result with no API behind it. This builds the
result a run gives for an upload of `data/demo/stops.csv` on the demo route once a
planner has left out every stop in review: the stops are snapped as in `import_upload`,
and the snapped ones are solved by the worker's own `solve_report`. It writes the
result in the shape a share link serves (`SharedRun`), plus a note of what it was built
from. Run from the repository root:

    uv run python -m starboard.worker.demo_result \
        --osm-extract cache/osm/extracts/connecticut-latest.osm.pbf

Without `--osm-extract` the street network comes from Overpass. The same stops and
OSM snapshot give the same files: an unchanged result keeps the time it was first built.
"""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from starboard.api.demo import DEMO_DIR, DEMO_ROUTE
from starboard.api.routers.routes import Location, RouteFields
from starboard.api.routers.runs import RunReport
from starboard.api.routers.shares import SharedRun
from starboard.geo.osm import (
    DEFAULT_CACHE_DIR,
    NETWORK_MARGIN_M,
    BoundingBox,
    bbox_around,
    fetch_network,
)
from starboard.geo.snapping import Snapper, snap_with
from starboard.geo.stop_file import read_stop_rows
from starboard.solver.fleet import trucks_for
from starboard.solver.graph import LonLat, StateGraph
from starboard.solver.objectives import RouteObjective
from starboard.worker.jobs import STREET_NOT_IN_NETWORK, comparison_request, solve_report

RESULT_DIR = DEMO_DIR / "result"
SHARED_RUN_FILE = "shared-run.json"
ABOUT_FILE = "about.json"
STOPS_FILE = "stops.csv"
ROUTE_FILE = "route.json"

DEMO_PLACE = "Byram, Greenwich, Connecticut"
# How data/demo/stops.csv's current order was drawn (scripts/build_demo_current_order.py),
# and how the baseline drives it (starboard.solver.baseline).
DEMO_CURRENT_ROUTE = (
    "It is a side-loader working a stop list drawn for a rear-loader, whose crew collects "
    "both curbs on one pass of each street with carts. For a cart on its left, the truck "
    "goes round to reach it from the right, or the driver gets out to bring it to the arm "
    "(a wrong-side pickup), whichever is quicker."
)

# Map coordinates are kept to about 0.1 m, finer than any map draws; it halves the file.
_COORDINATE_DECIMALS = 6
_SECONDS_PER_HOUR = 3600.0


class DemoAbout(BaseModel):
    """What the demo result was built from, shown beside it on the demo page."""

    place: str
    current_route_description: str
    stops_in_file: int
    stops_placed: int
    # Stops that go to a planner's review, by reason. The result leaves them all out of
    # both routes, as a planner can before a run.
    stops_in_review: dict[str, int]
    osm_snapshot: str | None
    # The SHA-256 of each input file, so a test can tell when the result is out of date.
    input_sha256: dict[str, str]


@dataclass(frozen=True, slots=True)
class DemoResult:
    shared: SharedRun
    about: DemoAbout


def _lon_lat(site: Location) -> LonLat:
    return LonLat(lon=site.lon, lat=site.lat)


# `solve_report` gives the report as JSON; RunReport validates it after rounding.
def _rounded(report: dict[str, Any]) -> dict[str, Any]:
    for side in ("current", "optimized"):
        for route in report[side]["routes"]:
            route["path"] = [
                [round(lon, _COORDINATE_DECIMALS), round(lat, _COORDINATE_DECIMALS)]
                for lon, lat in route["path"]
            ]
    return report


def build(
    stops_csv: bytes,
    route_json: bytes,
    network: Callable[[BoundingBox], StateGraph],
    clock: Callable[[], datetime],
) -> DemoResult:
    """The demo result for this stop file on this route (the bytes of `data/demo/`'s files).

    ValueError if the stop file has a row the importer would reject, a stop without
    lon/lat, or no stop that snaps."""
    stop_file = read_stop_rows(stops_csv.decode("utf-8-sig").splitlines(keepends=True))
    if stop_file.rejected:
        rows = "; ".join(f"line {r.line_number}: {r.reason}" for r in stop_file.rejected)
        raise ValueError(f"the demo stop file has rows the importer rejects: {rows}")
    if stop_file.unlocated:
        raise ValueError("every demo stop needs lon/lat; the demo build does not geocode")
    route = RouteFields.model_validate({"name": DEMO_ROUTE, **json.loads(route_json)})
    yard, disposal = _lon_lat(route.yard), _lon_lat(route.disposal)
    points = {s.stop_id: s for s in stop_file.stops}

    # As import_upload: one network around every stop and both sites; snap in current order.
    corners = [p.location for p in points.values()] + [yard, disposal]
    import_graph = network(bbox_around(corners, NETWORK_MARGIN_M))
    outcome = snap_with(Snapper(import_graph), [points[i] for i in stop_file.order])
    snapped = outcome.snapped
    if not snapped:
        raise ValueError("the upload has no snapped stops to solve")

    # As solve_run: a network around the snapped stops and both sites. A stop whose street
    # that network lacks is unserved, as the worker reports it.
    corners = [points[s.stop_id].location for s in snapped] + [yard, disposal]
    graph = network(bbox_around(corners, NETWORK_MARGIN_M))
    stops = [s for s in snapped if s.segment_id in graph.segments]
    missing = [
        {"stop_id": s.stop_id, "reason": STREET_NOT_IN_NETWORK}
        for s in snapped
        if s.segment_id not in graph.segments
    ]
    route_of = {
        s.stop_id: stop_file.route_of[s.stop_id] for s in snapped if s.stop_id in stop_file.route_of
    }
    request = comparison_request(
        route.capacity_carts,
        route.max_route_hours,
        # The trucks the API gives a run when the planner does not say (runs.start_run).
        trucks=max(len(set(route_of.values())), trucks_for(len(snapped))),
        objective=RouteObjective.BALANCED_TOTAL,
        route_of=route_of,
    )
    report = solve_report(graph, stops, missing, (yard, disposal), request)

    shared = SharedRun(
        route_name=route.name,
        finished_at=clock(),
        report=RunReport.model_validate(_rounded(report)),
    )
    about = DemoAbout(
        place=DEMO_PLACE,
        current_route_description=DEMO_CURRENT_ROUTE,
        stops_in_file=len(stop_file.order),
        stops_placed=len(snapped),
        stops_in_review=dict(sorted(Counter(r.reason.value for r in outcome.review).items())),
        osm_snapshot=graph.osm_snapshot,
        input_sha256={
            STOPS_FILE: hashlib.sha256(stops_csv).hexdigest(),
            ROUTE_FILE: hashlib.sha256(route_json).hexdigest(),
        },
    )
    return DemoResult(shared, about)


def write(result: DemoResult, out_dir: Path) -> None:
    """Write the result compactly and the note readably, both with sorted keys."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shared = result.shared.model_dump(mode="json")
    # LF on every platform, as the files are committed.
    (out_dir / SHARED_RUN_FILE).write_text(
        json.dumps(shared, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    about = result.about.model_dump(mode="json")
    (out_dir / ABOUT_FILE).write_text(
        json.dumps(about, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def read(out_dir: Path) -> DemoResult:
    """The result as `write` left it in `out_dir`."""
    return DemoResult(
        SharedRun.model_validate_json((out_dir / SHARED_RUN_FILE).read_text(encoding="utf-8")),
        DemoAbout.model_validate_json((out_dir / ABOUT_FILE).read_text(encoding="utf-8")),
    )


def keeping_built_time(result: DemoResult, written: DemoResult) -> DemoResult:
    """`result`, with the time `written` was built when nothing else differs, so an
    unchanged rebuild writes identical files."""
    if result.about != written.about or result.shared.report != written.shared.report:
        return result
    shared = result.shared.model_copy(update={"finished_at": written.shared.finished_at})
    return DemoResult(shared, result.about)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m starboard.worker.demo_result",
        description="Build the demo route's result for the static demo.",
    )
    parser.add_argument("--demo-dir", type=Path, default=DEMO_DIR)
    parser.add_argument("--out", type=Path, default=RESULT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--osm-extract",
        type=Path,
        help="build the network from this OSM extract (.osm.pbf) instead of Overpass",
    )
    args = parser.parse_args(argv)

    def network(bbox: BoundingBox) -> StateGraph:
        return fetch_network(bbox, cache_dir=args.cache_dir, extract=args.osm_extract)

    result = build(
        (args.demo_dir / STOPS_FILE).read_bytes(),
        (args.demo_dir / ROUTE_FILE).read_bytes(),
        network,
        clock=lambda: datetime.now(UTC).replace(microsecond=0),
    )
    # Nothing written yet, or written in another shape: the result is new.
    with suppress(FileNotFoundError, ValidationError):
        result = keeping_built_time(result, read(args.out))
    write(result, args.out)
    report = result.shared.report
    print(
        f"{result.about.stops_placed} of {result.about.stops_in_file} stops placed; "
        f"route time {report.current.area.route_time_s / _SECONDS_PER_HOUR:.2f} h current, "
        f"{report.optimized.area.route_time_s / _SECONDS_PER_HOUR:.2f} h optimized; "
        f"written to {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
