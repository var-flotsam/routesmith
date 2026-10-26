"""Exports of one run: the driver route sheet, stops in the new order, and route paths.

Each file is made when it is asked for, from the run's stored result, its upload's stops
and its route's name as it is now, and is not kept (ADR-0006): the same run under the
same route name gives the same bytes every time. Only members of the run's organization
can download them; a share link does not reach them.
"""

import re
import uuid
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from starlette.concurrency import run_in_threadpool

from starboard.api.deps import IN_ORG, Database, member
from starboard.api.models import Membership, Role, Route, Run, Stop
from starboard.api.routers.runs import RunReport
from starboard.api.scoping import in_org, one_in_org, result_in_org
from starboard.export.files import routes_gpx, routes_kml, stops_csv
from starboard.export.model import RunExport, Step, StopInfo, TruckRoute
from starboard.export.route_sheet import route_sheet_pdf

router = APIRouter(tags=["exports"])

Viewer = Annotated[Membership, Depends(member(Role.VIEWER))]


class ExportFile(StrEnum):
    ROUTE_SHEET_PDF = "route-sheet.pdf"
    STOPS_CSV = "stops.csv"
    ROUTES_GPX = "routes.gpx"
    ROUTES_KML = "routes.kml"


_MADE_BY: dict[ExportFile, Callable[[RunExport], bytes]] = {
    ExportFile.ROUTE_SHEET_PDF: route_sheet_pdf,
    ExportFile.STOPS_CSV: stops_csv,
    ExportFile.ROUTES_GPX: routes_gpx,
    ExportFile.ROUTES_KML: routes_kml,
}

# KML's is registered (https://www.iana.org/assignments/media-types/media-types.xhtml);
# GPX's is the one in common use, as GPX 1.1 registers none.
MEDIA_TYPES = {
    ExportFile.ROUTE_SHEET_PDF: "application/pdf",
    ExportFile.STOPS_CSV: "text/csv",
    ExportFile.ROUTES_GPX: "application/gpx+xml",
    ExportFile.ROUTES_KML: "application/vnd.google-earth.kml+xml",
}

_BINARY: dict[str, dict[str, str]] = {"schema": {"type": "string", "format": "binary"}}


def run_export(route_name: str, report: RunReport, stops: Iterable[StopInfo]) -> RunExport:
    """What the exports are made from: the run's optimized routes and its upload's stops."""
    return RunExport(
        route_name=route_name,
        osm_snapshot=report.osm_snapshot,
        routes=tuple(
            TruckRoute(
                order=tuple(route.order),
                path=tuple(route.path),
                steps=tuple(
                    Step(step.action.value, step.street, step.distance_m, tuple(step.stop_ids))
                    for step in route.steps
                ),
                route_time_s=route.scorecard.route_time_s,
                distance_m=route.scorecard.distance_m,
            )
            for route in report.optimized.routes
        ),
        stops={stop.stop_id: stop for stop in stops},
    )


def _stop_info(stop: Stop) -> StopInfo:
    point = None if stop.location is None else to_shape(stop.location)
    assert point is None or isinstance(point, Point)
    return StopInfo(
        stop_id=stop.stop_id,
        street=stop.street,
        lon=None if point is None else point.x,
        lat=None if point is None else point.y,
        current_route=stop.current_route_id,
        current_sequence=stop.current_sequence,
    )


def file_name(route_name: str, run: Run, file: ExportFile) -> str:
    """`byram-2026-10-26-route-sheet.pdf`: the route, the day the run finished, the file.

    ASCII letters, digits and hyphens only, so every browser saves it under that name."""
    route = re.sub(r"[^a-z0-9]+", "-", route_name.lower()).strip("-") or "route"
    day = (run.finished_at or run.created_at).date().isoformat()
    return f"{route}-{day}-{file.value}"


@router.get(
    "/orgs/{org_id}/runs/{run_id}/exports/{file}",
    response_class=Response,
    responses={
        **IN_ORG,
        200: {
            "description": "the file, to save: a PDF route sheet, a CSV of stops, GPX or KML",
            "content": {media_type: _BINARY for media_type in MEDIA_TYPES.values()},
        },
    },
)
async def download_export(
    org_id: uuid.UUID, run_id: uuid.UUID, file: ExportFile, db: Database, _: Viewer
) -> Response:
    """One of the run's exports, as a download. 404 until the run has succeeded."""
    run = await one_in_org(db, Run, org_id, run_id)
    report = RunReport.model_validate((await result_in_org(db, org_id, run_id)).result)
    route = await one_in_org(db, Route, org_id, run.route_id)
    stops = await db.scalars(in_org(Stop, org_id).where(Stop.upload_id == run.upload_id))
    export = run_export(route.name, report, (_stop_info(s) for s in stops))
    # Laying out a long route sheet takes a moment; it does not hold up other requests.
    data = await run_in_threadpool(_MADE_BY[file], export)
    return Response(
        data,
        media_type=MEDIA_TYPES[file],
        headers={
            "Content-Disposition": f'attachment; filename="{file_name(route.name, run, file)}"'
        },
    )
