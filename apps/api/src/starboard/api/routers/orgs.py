"""Organizations and their members."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from starboard.api.deps import IN_ORG, CurrentUser, Database, member
from starboard.api.models import Membership, Organization, Role, User
from starboard.api.security import EmailAddress, normalized_email
from starboard.api.text import Name

router = APIRouter(
    tags=["organizations"],
    responses={**IN_ORG, 409: {"description": "an organization keeps one owner"}},
)


class NewOrganization(BaseModel):
    name: Name


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class NewMember(BaseModel):
    email: EmailAddress
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    role: Role


@router.post("/orgs", status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: NewOrganization, user: CurrentUser, db: Database
) -> OrganizationOut:
    """A new organization, with the caller as its owner."""
    org = Organization(name=body.name.strip())
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER))
    await db.commit()
    return OrganizationOut(id=org.id, name=org.name)


@router.get("/orgs/{org_id}")
async def read_organization(
    org_id: uuid.UUID,
    db: Database,
    _: Annotated[Membership, Depends(member(Role.VIEWER))],
) -> OrganizationOut:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such organization")
    return OrganizationOut(id=org.id, name=org.name)


@router.get("/orgs/{org_id}/members")
async def list_members(
    org_id: uuid.UUID,
    db: Database,
    _: Annotated[Membership, Depends(member(Role.VIEWER))],
) -> list[MemberOut]:
    rows = await db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id)
        .order_by(User.email)
    )
    return [MemberOut(user_id=u.id, email=u.email, role=m.role) for m, u in rows.all()]


@router.put("/orgs/{org_id}/members", status_code=status.HTTP_200_OK)
async def add_member(
    org_id: uuid.UUID,
    body: NewMember,
    db: Database,
    _: Annotated[Membership, Depends(member(Role.OWNER))],
) -> MemberOut:
    """Add someone by email, or change their role; they sign in with a magic link."""
    email = normalized_email(body.email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        await db.flush()
    existing = await db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
    )
    if existing is None:
        db.add(Membership(org_id=org_id, user_id=user.id, role=body.role))
    else:
        if existing.role is Role.OWNER and body.role is not Role.OWNER:
            owners = await db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == Role.OWNER)
            )
            if owners == 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "an organization keeps one owner")
        existing.role = body.role
    await db.commit()
    return MemberOut(user_id=user.id, email=user.email, role=body.role)
