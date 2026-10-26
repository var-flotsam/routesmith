"""Stop uploads: the file, its processing state, and its stops, including the review queue."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select

from starboard.api.deps import Database, member
from starboard.api.models import Membership, Role, Route, Stop, StopState, Upload, UploadState
from starboard.api.queue import IMPORT_UPLOAD
from starboard.api.scoping import in_org, one_in_org

router = APIRouter(tags=["uploads"])

Viewer = Annotated[Membership, Depends(member(Role.VIEWER))]
Planner = Annotated[Membership, Depends(member(Role.PLANNER))]


class RejectedRowOut(BaseModel):
    line: int
    reason: str


class UploadOut(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    file_name: str
    state: UploadState
    rows_read: int
    rows_rejected: int
    stops_snapped: int
    stops_in_review: int
    rejected_rows: list[RejectedRowOut]
    osm_snapshot: str | None
    failure_reason: str | None
    created_at: datetime


class StopOut(BaseModel):
    stop_id: str
    current_sequence: int
    current_route_id: str | None
    street: str | None
    state: StopState
    segment_id: str | None
    curb_side: str | None
    review_reason: str | None
    review_detail: str | None
    candidate_segment_ids: list[str]


async def _out(db: Database, upload: Upload) -> UploadOut:
    counts = dict(
        (
            await db.execute(
                select(Stop.state, func.count())
                .where(Stop.org_id == upload.org_id, Stop.upload_id == upload.id)
                .group_by(Stop.state)
            )
        ).tuples()
    )
    return UploadOut(
        id=upload.id,
        route_id=upload.route_id,
        file_name=upload.file_name,
        state=upload.state,
        rows_read=upload.rows_read,
        rows_rejected=upload.rows_rejected,
        stops_snapped=counts.get(StopState.SNAPPED, 0),
        stops_in_review=counts.get(StopState.REVIEW, 0),
        rejected_rows=[RejectedRowOut(**r) for r in upload.rejected_rows],
        osm_snapshot=upload.osm_snapshot,
        failure_reason=upload.failure_reason,
        created_at=upload.created_at,
    )


@router.post("/orgs/{org_id}/routes/{route_id}/uploads", status_code=status.HTTP_202_ACCEPTED)
async def upload_stops(
    org_id: uuid.UUID,
    route_id: uuid.UUID,
    file: UploadFile,
    request: Request,
    db: Database,
    _: Planner,
) -> UploadOut:
    """Store a stop CSV and queue it to be read and snapped; poll the upload for its state."""
    route = await one_in_org(db, Route, org_id, route_id)
    limit = request.app.state.settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"files are limited to {limit} bytes"
        )
    upload_id = uuid.uuid4()
    key = f"{org_id}/uploads/{upload_id}.csv"
    await request.app.state.store.put(key, data)
    upload = Upload(
        id=upload_id,
        org_id=org_id,
        route_id=route.id,
        file_name=(file.filename or "stops.csv")[:255],
        object_key=key,
        state=UploadState.PROCESSING,
        rows_read=0,
        rows_rejected=0,
        rejected_rows=[],
    )
    db.add(upload)
    await db.commit()
    await request.app.state.queue.enqueue(IMPORT_UPLOAD, upload_id)
    return await _out(db, await one_in_org(db, Upload, org_id, upload_id))


@router.get("/orgs/{org_id}/routes/{route_id}/uploads")
async def list_uploads(
    org_id: uuid.UUID, route_id: uuid.UUID, db: Database, _: Viewer
) -> list[UploadOut]:
    await one_in_org(db, Route, org_id, route_id)
    uploads = await db.scalars(
        in_org(Upload, org_id)
        .where(Upload.route_id == route_id)
        .order_by(Upload.created_at.desc(), Upload.id)
    )
    return [await _out(db, u) for u in uploads.all()]


@router.get("/orgs/{org_id}/uploads/{upload_id}")
async def read_upload(
    org_id: uuid.UUID, upload_id: uuid.UUID, db: Database, _: Viewer
) -> UploadOut:
    return await _out(db, await one_in_org(db, Upload, org_id, upload_id))


@router.get("/orgs/{org_id}/uploads/{upload_id}/stops")
async def list_stops(
    org_id: uuid.UUID,
    upload_id: uuid.UUID,
    db: Database,
    _: Viewer,
    state: StopState | None = None,
) -> list[StopOut]:
    """The upload's stops in current order; `state=review` is the review queue."""
    await one_in_org(db, Upload, org_id, upload_id)
    query = in_org(Stop, org_id).where(Stop.upload_id == upload_id)
    if state is not None:
        query = query.where(Stop.state == state)
    stops = await db.scalars(query.order_by(Stop.current_sequence, Stop.stop_id))
    return [
        StopOut(
            stop_id=s.stop_id,
            current_sequence=s.current_sequence,
            current_route_id=s.current_route_id,
            street=s.street,
            state=s.state,
            segment_id=s.segment_id,
            curb_side=s.curb_side,
            review_reason=s.review_reason,
            review_detail=s.review_detail,
            candidate_segment_ids=s.candidate_segment_ids,
        )
        for s in stops
    ]
