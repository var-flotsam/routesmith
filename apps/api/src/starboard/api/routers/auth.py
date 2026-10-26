"""Sign-in by magic link, sign-out, and who is signed in."""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from starboard.api.deps import SESSION_COOKIE, SIGNED_IN, CurrentUser, Database, settings_of
from starboard.api.models import LoginToken, Membership, Organization, Role, Session, User
from starboard.api.security import EmailAddress, new_token, normalized_email, token_hash

router = APIRouter(tags=["auth"])


class MagicLinkRequest(BaseModel):
    email: EmailAddress


class OrgMembership(BaseModel):
    org_id: uuid.UUID
    name: str
    role: Role


class Me(BaseModel):
    id: uuid.UUID
    email: str
    organizations: list[OrgMembership]


@router.post("/auth/magic-link", status_code=status.HTTP_202_ACCEPTED)
async def send_magic_link(body: MagicLinkRequest, request: Request, db: Database) -> None:
    """Email a one-time sign-in link. Answers 202 for any address, known or not."""
    settings = settings_of(request)
    email = normalized_email(body.email)
    token = new_token()
    expires = datetime.now(UTC) + settings.login_token_ttl
    db.add(LoginToken(token_hash=token_hash(token), email=email, expires_at=expires))
    await db.commit()
    link = f"{settings.api_public_url}/auth/callback?{urlencode({'token': token})}"
    await request.app.state.email_sender.send_sign_in_link(email, link)


@router.get(
    "/auth/callback",
    status_code=status.HTTP_303_SEE_OTHER,
    responses={400: {"description": "the link has expired or was used"}},
)
async def sign_in(token: str, request: Request, db: Database) -> RedirectResponse:
    """Use a sign-in link: start a session and go to the app. A link works once."""
    settings = settings_of(request)
    now = datetime.now(UTC)
    login = await db.get(LoginToken, token_hash(token), with_for_update=True)
    if login is None or login.used_at is not None or login.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "this sign-in link has expired")
    login.used_at = now
    user = await db.scalar(select(User).where(User.email == login.email))
    if user is None:
        user = User(email=login.email)
        db.add(user)
        await db.flush()
    session_token = new_token()
    db.add(
        Session(
            token_hash=token_hash(session_token),
            user_id=user.id,
            expires_at=now + settings.session_ttl,
        )
    )
    await db.commit()
    response = RedirectResponse(settings.app_base_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=round(settings.session_ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/auth/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    db: Database, response: Response, starboard_session: str | None = Cookie(default=None)
) -> None:
    if starboard_session is not None:
        await db.execute(delete(Session).where(Session.token_hash == token_hash(starboard_session)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", responses=SIGNED_IN)
async def me(user: CurrentUser, db: Database) -> Me:
    rows = await db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name, Organization.id)
    )
    return Me(
        id=user.id,
        email=user.email,
        organizations=[
            OrgMembership(org_id=org.id, name=org.name, role=m.role) for m, org in rows.all()
        ],
    )
