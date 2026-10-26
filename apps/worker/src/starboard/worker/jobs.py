"""The worker's jobs. Each takes the arq context and one row id, and records its outcome.

`import_upload` reads an uploaded stop file, builds the street network around the
stops and the route's sites, and snaps every stop: a stop that snaps cleanly is
`snapped`, one the planner must place is `review` with the reason, and a row the
reader could not use is listed on the upload. A failure marks the upload `failed`
with the reason; it never leaves an upload `processing`.

`solve_run` rebuilds the network, places every snapped stop where the upload
recorded it (or where the planner placed it), and runs `comparison.compare`
off the event loop. The report is stored as the run's result; a failure marks
the run `failed` with the reason.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from starboard.api.models import (
    Route,
    Run,
    RunResult,
    RunState,
    Stop,
    StopState,
    Upload,
    UploadState,
)
from starboard.api.storage import ObjectStore
from starboard.geo.osm import NETWORK_MARGIN_M, BoundingBox, bbox_around
from starboard.geo.places import place_at
from starboard.geo.snapping import ReviewItem, Snapper, StopPoint, snap_stops
from starboard.geo.stop_file import read_stop_rows
from starboard.solver.comparison import ComparisonRequest, compare
from starboard.solver.graph import CurbSide, Direction, LonLat, Pass, SnappedStop, StateGraph
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings
from starboard.solver.route import RouteSites, TruckProfile

# Longer reasons are cut so the column always takes them.
_REASON_LENGTH = 500
_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class Context:
    """What jobs need, built once per worker process (see `starboard.worker.main`)."""

    sessions: async_sessionmaker[AsyncSession]
    store: ObjectStore
    network: Callable[[BoundingBox], StateGraph]  # blocking; runs in a thread
    # Runs the CPU-bound solve; the worker passes a process pool, tests run it in a thread.
    run_blocking: Callable[..., Awaitable[Any]] = asyncio.to_thread


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


def _stop_point(row: Stop) -> StopPoint:
    return StopPoint(row.stop_id, _lon_lat(row.location), street=row.street)


def _snapped(
    graph: StateGraph, rows: Sequence[Stop]
) -> tuple[list[SnappedStop], list[dict[str, str]]]:
    """The run's stops in current order, and those whose street is no longer in the network."""
    snapper = Snapper(graph)
    snapped: list[SnappedStop] = []
    missing: list[dict[str, str]] = []
    for row in rows:
        assert row.segment_id is not None and row.curb_side is not None
        if row.segment_id not in graph.segments:
            missing.append({"stop_id": row.stop_id, "reason": STREET_NOT_IN_NETWORK})
            continue
        side = CurbSide(row.curb_side)
        if row.distance_along_m is None or row.distance_from_centerline_m is None:
            snapped.append(snapper.place(_stop_point(row), row.segment_id, side))
            continue
        direction = Direction.FORWARD if side is CurbSide.RIGHT else Direction.REVERSE
        snapped.append(
            SnappedStop(
                stop_id=row.stop_id,
                segment_id=row.segment_id,
                distance_along_m=row.distance_along_m,
                distance_from_centerline_m=row.distance_from_centerline_m,
                side_of_forward=side,
                required_pass=Pass(row.segment_id, direction),
                street=row.street,
            )
        )
    return snapped, missing


# A stop placed on a street that a later network no longer has.
STREET_NOT_IN_NETWORK = "street_not_in_network"


async def solve_run(ctx: dict[str, Any], run_id: str) -> str:
    """Solve one run and store its report; returns its final state."""
    context = context_of(ctx)
    async with context.sessions() as db:
        run = await db.get(Run, uuid.UUID(run_id))
        if run is None:
            return "missing"
        run.state = RunState.RUNNING
        run.started_at = datetime.now(UTC)
        await db.commit()
        try:
            await _solve(db, context, run)
        except Exception as error:  # every failure becomes the run's reason
            await db.rollback()
            run = await db.get(Run, uuid.UUID(run_id))
            assert run is not None
            run.state = RunState.FAILED
            run.failure_reason = f"{type(error).__name__}: {error}"[:_REASON_LENGTH]
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return run.state.value


async def _solve(db: AsyncSession, context: Context, run: Run) -> None:
    route = await db.get(Route, run.route_id)
    assert route is not None
    rows = (
        await db.scalars(
            select(Stop)
            .where(Stop.upload_id == run.upload_id, Stop.state == StopState.SNAPPED)
            .order_by(Stop.current_sequence, Stop.stop_id)
        )
    ).all()
    if not rows:
        raise ValueError("the upload has no snapped stops to solve")
    yard, disposal = _lon_lat(route.yard), _lon_lat(route.disposal)
    bbox = bbox_around([*(_lon_lat(r.location) for r in rows), yard, disposal], NETWORK_MARGIN_M)
    graph = await asyncio.to_thread(context.network, bbox)
    stops, missing = _snapped(graph, rows)
    sites = RouteSites(place_at(graph, "yard", yard), place_at(graph, "disposal", disposal))
    hours = route.max_route_hours
    profile = TruckProfile(
        capacity_carts=route.capacity_carts,
        max_route_duration_s=None if hours is None else hours * _SECONDS_PER_HOUR,
    )
    request = ComparisonRequest(
        trucks=run.trucks,
        objective=RouteObjective(run.objective),
        settings=SolveSettings(profile),
        route_of={r.stop_id: r.current_route_id for r in rows if r.current_route_id},
    )
    report = await context.run_blocking(compare, graph, stops, sites, request)
    report["unserved"] = [*report["unserved"], *missing]
    report["osm_snapshot"] = graph.osm_snapshot
    db.add(RunResult(run_id=run.id, org_id=run.org_id, result=report))
    run.state = RunState.SUCCEEDED
    run.osm_snapshot = graph.osm_snapshot
    run.solver_version = metadata.version("starboard-solver")
