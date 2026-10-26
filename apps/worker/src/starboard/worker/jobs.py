"""The worker's jobs. Each takes the arq context and one row id, and records its outcome.

`import_upload` reads an uploaded stop file, builds the street network around the
stops and the route's sites, and snaps every stop: a stop that snaps cleanly is
`snapped`, one the planner must place is `review` with the reason, and a row the
reader could not use is listed on the upload. A failure marks the upload `failed`
with the reason; it never leaves an upload `processing`.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from starboard.api.models import Route, Stop, StopState, Upload, UploadState
from starboard.api.storage import ObjectStore
from starboard.geo.osm import NETWORK_MARGIN_M, BoundingBox, bbox_around
from starboard.geo.snapping import ReviewItem, StopPoint, snap_stops
from starboard.geo.stop_file import read_stop_rows
from starboard.solver.graph import LonLat, SnappedStop, StateGraph

# Longer reasons are cut so the column always takes them.
_REASON_LENGTH = 500


@dataclass(frozen=True, slots=True)
class Context:
    """What jobs need, built once per worker process (see `starboard.worker.main`)."""

    sessions: async_sessionmaker[AsyncSession]
    store: ObjectStore
    network: Callable[[BoundingBox], StateGraph]  # blocking; runs in a thread


def context_of(ctx: dict[str, Any]) -> Context:
    found = ctx["starboard"]
    assert isinstance(found, Context)
    return found


def _lon_lat(value: WKBElement) -> LonLat:
    shape = to_shape(value)
    assert isinstance(shape, Point)
    return LonLat(lon=shape.x, lat=shape.y)


def _point(location: LonLat) -> WKBElement:
    return from_shape(Point(location.lon, location.lat), srid=4326)


async def import_upload(ctx: dict[str, Any], upload_id: str) -> str:
    """Read and snap one upload; returns its final state."""
    context = context_of(ctx)
    async with context.sessions() as db:
        upload = await db.get(Upload, uuid.UUID(upload_id))
        if upload is None:
            return "missing"
        try:
            await _import(db, context, upload)
        except Exception as error:  # every failure becomes the upload's reason
            await db.rollback()
            upload = await db.get(Upload, uuid.UUID(upload_id))
            assert upload is not None
            upload.state = UploadState.FAILED
            upload.failure_reason = f"{type(error).__name__}: {error}"[:_REASON_LENGTH]
        await db.commit()
        return upload.state.value


async def _import(db: AsyncSession, context: Context, upload: Upload) -> None:
    route = await db.get(Route, upload.route_id)
    assert route is not None
    text = (await context.store.get(upload.object_key)).decode("utf-8-sig")
    stop_file = read_stop_rows(text.splitlines(keepends=True))
    upload.rows_read = len(stop_file.stops) + len(stop_file.rejected)
    upload.rows_rejected = len(stop_file.rejected)
    upload.rejected_rows = [{"line": r.line_number, "reason": r.reason} for r in stop_file.rejected]
    await db.execute(delete(Stop).where(Stop.upload_id == upload.id))
    if stop_file.stops:
        points = [s.location for s in stop_file.stops]
        points += [_lon_lat(route.yard), _lon_lat(route.disposal)]
        bbox = bbox_around(points, NETWORK_MARGIN_M)
        graph = await asyncio.to_thread(context.network, bbox)
        outcome = await asyncio.to_thread(snap_stops, graph, stop_file.stops)
        upload.osm_snapshot = graph.osm_snapshot
        placed: dict[str, SnappedStop | ReviewItem] = {s.stop_id: s for s in outcome.snapped}
        placed.update({r.stop_id: r for r in outcome.review})
        for sequence, stop in enumerate(stop_file.stops, start=1):
            route_id = stop_file.route_of.get(stop.stop_id)
            db.add(_row(upload, sequence, stop, route_id, placed[stop.stop_id]))
    upload.state = UploadState.READY


def _row(
    upload: Upload,
    sequence: int,
    stop: StopPoint,
    route_id: str | None,
    placed: SnappedStop | ReviewItem,
) -> Stop:
    row = Stop(
        org_id=upload.org_id,
        upload_id=upload.id,
        stop_id=stop.stop_id,
        current_sequence=sequence,
        current_route_id=route_id,
        location=_point(stop.location),
        street=stop.street,
    )
    if isinstance(placed, SnappedStop):
        row.state = StopState.SNAPPED
        row.segment_id = placed.segment_id
        row.curb_side = placed.side_of_forward.value
        row.required_direction = placed.required_pass.direction.value
        row.distance_along_m = placed.distance_along_m
        row.distance_from_centerline_m = placed.distance_from_centerline_m
    else:
        row.state = StopState.REVIEW
        row.review_reason = placed.reason.value
        row.review_detail = placed.detail[:_REASON_LENGTH]
        row.candidate_segment_ids = list(placed.candidate_segment_ids)
    return row
