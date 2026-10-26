"""Read-only share links: one run's result, for someone outside the organization.

A planner makes a link (which replaces any earlier link to that run) or takes it
away; anyone with the link reads the result and the route's name, nothing else.
The link's token is shown once and stored only as a hash.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select

from starboard.api.deps import IN_ORG, CurrentUser, Database, member, settings_of
from starboard.api.models import Membership, Role, Route, Run, RunResult, RunState, ShareLink
from starboard.api.routers.runs import RunReport
from starboard.api.scoping import one_in_org
from starboard.api.security import new_token, token_hash

router = APIRouter(tags=["share links"])

Viewer = Annotated[Membership, Depends(member(Role.VIEWER))]
Planner = Annotated[Membership, Depends(member(Role.PLANNER))]


class NewShareLink(BaseModel):
    url: str  # shown once; only its hash is kept
    created_at: datetime


class ShareLinkState(BaseModel):
    shared: bool
    created_at: datetime | None


class SharedRun(BaseModel):
    """What a share link shows: the route's name, when the run finished, and its report."""

    route_name: str
    finished_at: datetime | None
    report: RunReport


@router.put(
    "/orgs/{org_id}/runs/{run_id}/share-link",
    responses={**IN_ORG, 409: {"description": "the run has not succeeded"}},
)
async def share_run(
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    db: Database,
    user: CurrentUser,
    _: Planner,
) -> NewShareLink:
    """Make a read-only link to the run's result; any earlier link to it stops working."""
    run = await one_in_org(db, Run, org_id, run_id)
    if run.state is not RunState.SUCCEEDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "only a finished run can be shared")
    await db.execute(delete(ShareLink).where(ShareLink.run_id == run.id))
    token = new_token()
    link = ShareLink(token_hash=token_hash(token), org_id=org_id, run_id=run.id, created_by=user.id)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return NewShareLink(
        url=f"{settings_of(request).app_base_url}/shared/{token}", created_at=link.created_at
    )


@router.get("/orgs/{org_id}/runs/{run_id}/share-link", responses=IN_ORG)
async def share_state(
    org_id: uuid.UUID, run_id: uuid.UUID, db: Database, _: Viewer
) -> ShareLinkState:
    run = await one_in_org(db, Run, org_id, run_id)
    link = await db.scalar(
        select(ShareLink).where(ShareLink.org_id == org_id, ShareLink.run_id == run.id)
    )
    return ShareLinkState(shared=link is not None, created_at=link.created_at if link else None)


@router.delete(
    "/orgs/{org_id}/runs/{run_id}/share-link",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=IN_ORG,
)
async def stop_sharing(org_id: uuid.UUID, run_id: uuid.UUID, db: Database, _: Planner) -> Response:
    run = await one_in_org(db, Run, org_id, run_id)
    await db.execute(
        delete(ShareLink).where(ShareLink.org_id == org_id, ShareLink.run_id == run.id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/shared/{token}", responses={404: {"description": "no such link, or it was taken away"}}
)
async def read_shared(token: str, db: Database) -> SharedRun:
    """A shared run's result. Needs no sign-in: the link is the permission."""
    link = await db.get(ShareLink, token_hash(token))
    found = None
    if link is not None:
        found = (
            await db.execute(
                select(Run, Route, RunResult)
                .join(Route, Route.id == Run.route_id)
                .join(RunResult, RunResult.run_id == Run.id)
                .where(Run.id == link.run_id, Run.org_id == link.org_id)
            )
        ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such link")
    run, route, result = found
    return SharedRun(
        route_name=route.name,
        finished_at=run.finished_at,
        report=RunReport.model_validate(result.result),
    )
