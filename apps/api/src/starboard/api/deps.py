"""Request dependencies: the database session, the signed-in user, and org membership.

Org scoping (ADR-0004): every route under `/orgs/{org_id}` resolves the caller's
membership here. A caller with no membership in that organization gets 404, the
same as an organization that does not exist; a member whose role is too low
gets 403.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from starboard.api.models import Membership, Role, Session, User
from starboard.api.security import token_hash
from starboard.api.settings import Settings

SESSION_COOKIE = "starboard_session"

# Each role can do everything the roles after it can.
_RANK = {Role.OWNER: 3, Role.PLANNER: 2, Role.VIEWER: 1}


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def database(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


Database = Annotated[AsyncSession, Depends(database)]


async def current_user(
    db: Database,
    request: Request,
    starboard_session: Annotated[str | None, Cookie()] = None,
) -> User:
    """The signed-in user; 401 without a live session. Using a session extends it."""
    if starboard_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    session = await db.get(Session, token_hash(starboard_session))
    now = datetime.now(UTC)
    if session is None or session.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    session.last_seen_at = now
    session.expires_at = now + settings_of(request).session_ttl
    user = await db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    await db.commit()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def membership(db: AsyncSession, user: User, org_id: uuid.UUID, at_least: Role) -> Membership:
    """The caller's membership of `org_id`: 404 if none, 403 if the role is below `at_least`."""
    found = await db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user.id)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such organization")
    if _RANK[found.role] < _RANK[at_least]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"needs the {at_least.value} role")
    return found


def member(
    at_least: Role,
) -> Callable[[uuid.UUID, User, AsyncSession], Coroutine[None, None, Membership]]:
    """A dependency resolving the caller's membership of the path's `org_id`."""

    async def check(org_id: uuid.UUID, user: CurrentUser, db: Database) -> Membership:
        return await membership(db, user, org_id, at_least)

    return check
