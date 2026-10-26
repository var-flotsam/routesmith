"""The one place org-owned rows are read: every lookup is filtered by organization.

Routers never query org-owned tables directly (ADR-0004). A row in another
organization is reported exactly like a missing row.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from starboard.api.models import Route as RouteRow
from starboard.api.models import Run, RunResult, Stop, Upload

# The tables whose rows belong to one organization and are reached by id.
type OrgOwned = RouteRow | Upload | Stop | Run


def in_org[Row: OrgOwned](model: type[Row], org_id: uuid.UUID) -> Select[Row]:
    """`SELECT model WHERE org_id = :org`; add filters and ordering to it."""
    return select(model).where(model.org_id == org_id)


async def one_in_org[Row: OrgOwned](
    db: AsyncSession, model: type[Row], org_id: uuid.UUID, row_id: uuid.UUID
) -> Row:
    """The row with this id in this organization, or 404."""
    found = await db.scalar(in_org(model, org_id).where(model.id == row_id))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such {model.__tablename__[:-1]}")
    return found


async def result_in_org(db: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> RunResult:
    """A run's result in this organization, or 404."""
    found = await db.scalar(
        select(RunResult).where(RunResult.org_id == org_id, RunResult.run_id == run_id)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such result")
    return found
