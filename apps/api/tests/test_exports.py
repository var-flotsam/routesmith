"""Exports: each of a run's files downloads, the same bytes every time, only within its org."""

import csv
import io
from datetime import UTC, datetime

import pytest

from starboard.api.models import Run
from starboard.api.routers.exports import ExportFile, file_name, run_export
from starboard.api.routers.runs import RunReport
from starboard.export.files import stops_csv
from starboard.export.model import StopInfo
from starboard.export.route_sheet import route_sheet_pdf
from starboard.geo.snapping import Snapper, StopPoint
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.comparison import ComparisonRequest, compare
from starboard.solver.graph import Place, SnappedStop
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites

GRID = Grid()  # the grid the test harness builds the network from


def _site(x, y):
    point = GRID.at(x, y)
    return {"lon": point.lon, "lat": point.lat}


def _report() -> RunReport:
    graph = build_state_graph(GRID.segments())
    snapper = Snapper(graph)
    stops = [snapper.snap(StopPoint(f"s{k}", GRID.at(x, -10))) for k, x in enumerate((20, 60))]
    assert all(isinstance(s, SnappedStop) for s in stops)
    request = ComparisonRequest(
        1, RouteObjective.BALANCED_TOTAL, SolveSettings(solution_limit=30), {}
    )
    report = compare(graph, stops, RouteSites(Place("yard", 0), Place("disposal", 0)), request)
    report["osm_snapshot"] = "2026-10-01"
    return RunReport.model_validate(report)


def test_a_run_report_becomes_the_exports_input():
    report = _report()
    stops = [
        StopInfo("s0", "Grid St", -73.6, 41.0, "A", 1),
        StopInfo("s1", None, None, None, None, 2),
    ]
    export = run_export("Grid", report, stops)
    (route,) = export.routes
    (optimized,) = report.optimized.routes
    assert route.order == tuple(optimized.order)
    assert [s.action for s in route.steps] == [s.action.value for s in optimized.steps]
    assert route.route_time_s == optimized.scorecard.route_time_s
    assert export.osm_snapshot == "2026-10-01"
    assert set(export.stops) == {"s0", "s1"}
    rows = list(csv.DictReader(io.StringIO(stops_csv(export).decode())))
    assert [r["stop_id"] for r in rows] == list(optimized.order)
    assert route_sheet_pdf(export).startswith(b"%PDF")


def test_a_file_is_named_for_its_route_and_the_day_the_run_finished():
    run = Run(
        created_at=datetime(2026, 10, 25, 23, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 26, 1, 0, tzinfo=UTC),
    )
    assert file_name("Byram & Mill (west)", run, ExportFile.ROUTE_SHEET_PDF) == (
        "byram-mill-west-2026-10-26-route-sheet.pdf"
    )
    assert file_name("Öst / 東", run, ExportFile.STOPS_CSV) == "st-2026-10-26-stops.csv"
    assert file_name("東", run, ExportFile.ROUTES_KML) == "route-2026-10-26-routes.kml"


async def _solved_run(api, email="planner@example.com"):
    client = await api.signed_in(email)
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    body = {"name": "Grid", "yard": _site(0, 0), "disposal": _site(0, 0), "capacity_carts": 2}
    route = (await client.post(f"/orgs/{org}/routes", json=body)).json()["id"]
    rows = ["stop_id,current_sequence,lon,lat"]
    for k, (x, y) in enumerate([(20, -10), (60, -10)], start=1):
        p = GRID.at(x, y)
        rows.append(f"s{k},{k},{p.lon},{p.lat}")
    files = {"file": ("stops.csv", ("\n".join(rows) + "\n").encode(), "text/csv")}
    upload = (await client.post(f"/orgs/{org}/routes/{route}/uploads", files=files)).json()
    await api.run_jobs()
    run = (
        await client.post(
            f"/orgs/{org}/routes/{route}/runs",
            json={"upload_id": upload["id"], "objective": "balanced-total"},
        )
    ).json()
    await api.run_jobs()
    return client, org, run["id"]


@pytest.mark.anyio
async def test_every_export_downloads_as_a_named_file(api):
    client, org, run = await _solved_run(api)
    expected = {
        ExportFile.ROUTE_SHEET_PDF: ("application/pdf", b"%PDF"),
        ExportFile.STOPS_CSV: ("text/csv; charset=utf-8", b"route,sequence,stop_id"),
        ExportFile.ROUTES_GPX: ("application/gpx+xml", b"<?xml"),
        ExportFile.ROUTES_KML: ("application/vnd.google-earth.kml+xml", b"<?xml"),
    }
    for file, (media_type, start) in expected.items():
        response = await client.get(f"/orgs/{org}/runs/{run}/exports/{file.value}")
        assert response.status_code == 200, (file, response.text)
        assert response.headers["content-type"] == media_type
        disposition = response.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="grid-')
        assert disposition.endswith(f'-{file.value}"')
        assert response.content.startswith(start)
        again = await client.get(f"/orgs/{org}/runs/{run}/exports/{file.value}")
        assert again.content == response.content  # the same run, the same bytes


@pytest.mark.anyio
async def test_the_csv_lists_the_stops_in_the_optimized_order(api):
    client, org, run = await _solved_run(api)
    result = (await client.get(f"/orgs/{org}/runs/{run}/result")).json()
    (optimized,) = result["optimized"]["routes"]
    data = (await client.get(f"/orgs/{org}/runs/{run}/exports/stops.csv")).text
    rows = list(csv.DictReader(io.StringIO(data)))
    assert [r["stop_id"] for r in rows] == optimized["order"]
    assert all(r["lon"] and r["lat"] for r in rows)
    assert [r["current_sequence"] for r in sorted(rows, key=lambda r: r["stop_id"])] == ["1", "2"]


@pytest.mark.anyio
async def test_a_viewer_can_download_and_a_stranger_cannot(api):
    client, org, run = await _solved_run(api)
    await client.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    path = f"/orgs/{org}/runs/{run}/exports/route-sheet.pdf"
    assert (await viewer.get(path)).status_code == 200
    assert (await api.client().get(path)).status_code == 401


@pytest.mark.anyio
async def test_another_organization_cannot_download(api):
    _, alice_org, run = await _solved_run(api, "alice@example.com")
    bob = await api.signed_in("bob@example.com")
    bob_org = (await bob.post("/orgs", json={"name": "Bob Hauling"})).json()["id"]
    for org in (alice_org, bob_org):
        for file in ExportFile:
            response = await bob.get(f"/orgs/{org}/runs/{run}/exports/{file.value}")
            assert response.status_code == 404, (org, file)


@pytest.mark.anyio
async def test_a_run_without_a_result_has_no_exports(api):
    client = await api.signed_in("planner@example.com")
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    body = {"name": "Grid", "yard": _site(0, 0), "disposal": _site(0, 0)}
    route = (await client.post(f"/orgs/{org}/routes", json=body)).json()["id"]
    rows = "stop_id,current_sequence,lon,lat\n" + f"s1,1,{_site(20, -10)['lon']},"
    rows += f"{_site(20, -10)['lat']}\n"
    files = {"file": ("stops.csv", rows.encode(), "text/csv")}
    upload = (await client.post(f"/orgs/{org}/routes/{route}/uploads", files=files)).json()
    await api.run_jobs()
    run = (
        await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload["id"]})
    ).json()  # queued, not yet solved
    response = await client.get(f"/orgs/{org}/runs/{run['id']}/exports/stops.csv")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_an_unknown_file_is_a_validation_error(api):
    client, org, run = await _solved_run(api)
    assert (await client.get(f"/orgs/{org}/runs/{run}/exports/route.docx")).status_code == 422
