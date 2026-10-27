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
from starboard.geo.geocoding import GeocodeQuality, Geocoder, geocode_all
from starboard.geo.osm import NETWORK_MARGIN_M, BoundingBox, bbox_around
from starboard.geo.places import place_at
from starboard.geo.snapping import (
    Candidate,
    ReviewItem,
    ReviewReason,
    Snapper,
    StopPoint,
    snap_with,
)
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
    geocoder: Geocoder  # blocking; runs in a thread
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
    readable = len(stop_file.stops) + len(stop_file.unlocated)
    upload.rows_read = readable + len(stop_file.rejected)
    upload.rows_rejected = len(stop_file.rejected)
    upload.rejected_rows = [{"line": r.line_number, "reason": r.reason} for r in stop_file.rejected]
    await db.execute(delete(Stop).where(Stop.upload_id == upload.id))

    # Stops given by address only are geocoded in one batch.
    geocoded = await asyncio.to_thread(
        geocode_all, context.geocoder, [(u.stop_id, u.address) for u in stop_file.unlocated]
    )
    points = {s.stop_id: s for s in stop_file.stops}
    for unlocated in stop_file.unlocated:
        if unlocated.stop_id in geocoded.points:
            location = geocoded.points[unlocated.stop_id]
            points[unlocated.stop_id] = StopPoint(unlocated.stop_id, location, unlocated.street)
    placed: dict[str, SnappedStop | ReviewItem] = {
        stop_id: ReviewItem(stop_id, _UNPLACED[quality], "the geocoder could not place it")
        for stop_id, quality in geocoded.unplaced.items()
    }
    if points:
        corners = [p.location for p in points.values()]
        corners += [_lon_lat(route.yard), _lon_lat(route.disposal)]
        graph = await asyncio.to_thread(context.network, bbox_around(corners, NETWORK_MARGIN_M))
        upload.osm_snapshot = graph.osm_snapshot
        in_order = [points[i] for i in stop_file.order if i in points]
        snapper = await asyncio.to_thread(Snapper, graph)
        outcome = await asyncio.to_thread(snap_with, snapper, in_order)
        placed.update({r.stop_id: r for r in outcome.review})
        for snapped in outcome.snapped:
            if snapped.stop_id in geocoded.inexact:
                # The geocoder changed the address to place it: a planner confirms the street.
                detail = (
                    f"placed as {geocoded.matched_address.get(snapped.stop_id, 'a nearby address')}"
                )
                placed[snapped.stop_id] = ReviewItem(
                    snapped.stop_id, ReviewReason.ADDRESS_INEXACT, detail, (snapped.segment_id,)
                )
            else:
                placed[snapped.stop_id] = snapped
    # Each street a stop in review could be on, drawn, for the planner to pick on the map.
    candidates: dict[str, list[dict[str, Any]]] = {}
    for stop_id, item in placed.items():
        if isinstance(item, ReviewItem) and item.candidate_segment_ids and stop_id in points:
            candidates[stop_id] = [
                _candidate_json(snapper.candidate(points[stop_id], segment_id))
                for segment_id in item.candidate_segment_ids
            ]
    streets = {u.stop_id: u.street for u in stop_file.unlocated}
    for sequence, stop_id in enumerate(stop_file.order, start=1):
        point = points.get(stop_id)
        row = Stop(
            org_id=upload.org_id,
            upload_id=upload.id,
            stop_id=stop_id,
            current_sequence=sequence,
            current_route_id=stop_file.route_of.get(stop_id),
            location=None if point is None else _point(point.location),
            street=point.street if point is not None else streets.get(stop_id),
        )
        row.candidate_streets = candidates.get(stop_id, [])
        db.add(_placed(row, placed[stop_id]))
    upload.state = UploadState.READY


def _candidate_json(candidate: Candidate) -> dict[str, Any]:
    return {
        "segment_id": candidate.segment_id,
        "name": candidate.name,
        "curb_side": candidate.side_of_forward.value,
        "line": [[p.lon, p.lat] for p in candidate.geometry],
    }


_UNPLACED = {
    GeocodeQuality.NOT_FOUND: ReviewReason.ADDRESS_NOT_FOUND,
    GeocodeQuality.AMBIGUOUS: ReviewReason.ADDRESS_AMBIGUOUS,
}


def _placed(row: Stop, placed: SnappedStop | ReviewItem) -> Stop:
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


def _location_of(row: Stop) -> LonLat:
    """A snapped stop always has a location; only unplaced addresses lack one."""
    assert row.location is not None, row.stop_id
    return _lon_lat(row.location)


def _stop_point(row: Stop) -> StopPoint:
    return StopPoint(row.stop_id, _location_of(row), street=row.street)


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


def comparison_request(
    capacity_carts: int | None,
    max_route_hours: float | None,
    trucks: int,
    objective: RouteObjective,
    route_of: dict[str, str],
) -> ComparisonRequest:
    """What a run asks of `compare`, from its route's truck and the run's settings."""
    duration_s = None if max_route_hours is None else max_route_hours * _SECONDS_PER_HOUR
    profile = TruckProfile(capacity_carts=capacity_carts, max_route_duration_s=duration_s)
    return ComparisonRequest(
        trucks=trucks, objective=objective, settings=SolveSettings(profile), route_of=route_of
    )


def solve_report(
    graph: StateGraph,
    stops: Sequence[SnappedStop],
    missing: Sequence[dict[str, str]],
    sites: tuple[LonLat, LonLat],
    request: ComparisonRequest,
) -> dict[str, Any]:  # the report as JSON, stored as the run's result
    """A run's report: `compare` from the yard to the disposal site, with the stops whose
    street the network lacks (`missing`) as unserved. Module-level, so a process pool runs it."""
    yard, disposal = sites
    route_sites = RouteSites(place_at(graph, "yard", yard), place_at(graph, "disposal", disposal))
    report = compare(graph, stops, route_sites, request)
    report["unserved"] = [*report["unserved"], *missing]
    report["osm_snapshot"] = graph.osm_snapshot
    return report


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
    bbox = bbox_around([*(_location_of(r) for r in rows), yard, disposal], NETWORK_MARGIN_M)
    graph = await asyncio.to_thread(context.network, bbox)
    stops, missing = _snapped(graph, rows)
    request = comparison_request(
        route.capacity_carts,
        route.max_route_hours,
        trucks=run.trucks,
        objective=RouteObjective(run.objective),
        route_of={r.stop_id: r.current_route_id for r in rows if r.current_route_id},
    )
    report = await context.run_blocking(
        solve_report, graph, stops, missing, (yard, disposal), request
    )
    db.add(RunResult(run_id=run.id, org_id=run.org_id, result=report))
    run.state = RunState.SUCCEEDED
    run.osm_snapshot = graph.osm_snapshot
    run.solver_version = metadata.version("starboard-solver")
