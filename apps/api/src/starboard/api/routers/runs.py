"""Runs: solve an upload's stops for a route, then read the result."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from starboard.api.deps import Database, member
from starboard.api.models import (
    Membership,
    Role,
    Route,
    Run,
    RunState,
    Stop,
    StopState,
    Upload,
    UploadState,
)
from starboard.api.queue import SOLVE_RUN
from starboard.api.scoping import in_org, one_in_org, result_in_org
from starboard.solver.fleet import trucks_for
from starboard.solver.objectives import RouteObjective, check_objective

router = APIRouter(tags=["runs"])

Viewer = Annotated[Membership, Depends(member(Role.VIEWER))]
Planner = Annotated[Membership, Depends(member(Role.PLANNER))]

# More trucks than this in one area is a request error, not a plan.
_MAX_TRUCKS = 100
_SECONDS_PER_HOUR = 3600.0


class NewRun(BaseModel):
    upload_id: uuid.UUID
    trucks: int | None = Field(
        default=None,
        ge=1,
        le=_MAX_TRUCKS,
        description="default: the number of current routes, and enough that no route is over "
        "the stop limit",
    )
    objective: RouteObjective = RouteObjective.BALANCED_TOTAL


class RunOut(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    upload_id: uuid.UUID
    state: RunState
    trucks: int
    objective: RouteObjective
    osm_snapshot: str | None
    solver_version: str | None
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _out(run: Run) -> RunOut:
    return RunOut(
        id=run.id,
        route_id=run.route_id,
        upload_id=run.upload_id,
        state=run.state,
        trucks=run.trucks,
        objective=RouteObjective(run.objective),
        osm_snapshot=run.osm_snapshot,
        solver_version=run.solver_version,
        failure_reason=run.failure_reason,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post("/orgs/{org_id}/routes/{route_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    org_id: uuid.UUID,
    route_id: uuid.UUID,
    body: NewRun,
    request: Request,
    db: Database,
    _: Planner,
) -> RunOut:
    """Queue a solve of the upload's stops; poll the run for its state."""
    route = await one_in_org(db, Route, org_id, route_id)
    upload = await one_in_org(db, Upload, org_id, body.upload_id)
    if upload.route_id != route.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such upload for this route")
    if upload.state is not UploadState.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, f"the upload is {upload.state.value}")
    counts = dict(
        (state, count)
        for state, count in (
            await db.execute(
                select(Stop.state, func.count())
                .where(Stop.org_id == org_id, Stop.upload_id == upload.id)
                .group_by(Stop.state)
            )
        ).all()
    )
    if counts.get(StopState.REVIEW, 0):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{counts[StopState.REVIEW]} stops are still in review"
        )
    snapped = counts.get(StopState.SNAPPED, 0)
    if not snapped:
        raise HTTPException(status.HTTP_409_CONFLICT, "the upload has no stops to solve")
    max_s = None if route.max_route_hours is None else route.max_route_hours * _SECONDS_PER_HOUR
    try:
        check_objective(body.objective, max_s)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    trucks = body.trucks
    if trucks is None:
        current_routes = await db.scalar(
            select(func.count(func.distinct(Stop.current_route_id))).where(
                Stop.org_id == org_id,
                Stop.upload_id == upload.id,
                Stop.state == StopState.SNAPPED,
            )
        )
        trucks = max(current_routes or 0, trucks_for(snapped))
    run = Run(
        org_id=org_id,
        route_id=route.id,
        upload_id=upload.id,
        state=RunState.QUEUED,
        trucks=trucks,
        objective=body.objective.value,
    )
    db.add(run)
    await db.commit()
    await request.app.state.queue.enqueue(SOLVE_RUN, run.id)
    return _out(await one_in_org(db, Run, org_id, run.id))


@router.get("/orgs/{org_id}/routes/{route_id}/runs")
async def list_runs(
    org_id: uuid.UUID, route_id: uuid.UUID, db: Database, _: Viewer
) -> list[RunOut]:
    await one_in_org(db, Route, org_id, route_id)
    runs = await db.scalars(
        in_org(Run, org_id).where(Run.route_id == route_id).order_by(Run.created_at.desc(), Run.id)
    )
    return [_out(r) for r in runs]


@router.get("/orgs/{org_id}/runs/{run_id}")
async def read_run(org_id: uuid.UUID, run_id: uuid.UUID, db: Database, _: Viewer) -> RunOut:
    return _out(await one_in_org(db, Run, org_id, run_id))


@router.get("/orgs/{org_id}/runs/{run_id}/result")
async def read_result(
    org_id: uuid.UUID, run_id: uuid.UUID, db: Database, _: Viewer
) -> dict[str, Any]:
    """The run's report: current and optimized scorecards, orders, bound, gap and unserved
    stops, as the solver computed them. 404 until the run has succeeded."""
    await one_in_org(db, Run, org_id, run_id)
    return (await result_in_org(db, org_id, run_id)).result
