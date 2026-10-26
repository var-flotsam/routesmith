"""Sign-in, sessions, organizations and members, including the cross-org negative tests."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select, update

from starboard.api.models import LoginToken, Session, User

pytestmark = pytest.mark.anyio


async def test_a_magic_link_signs_in_and_creates_the_user(api):
    client = await api.signed_in("Planner@Example.com")
    me = (await client.get("/me")).json()
    assert me["email"] == "planner@example.com"
    assert me["organizations"] == []


async def test_a_magic_link_is_sent_for_any_address_and_creates_no_user(api):
    client = api.client()
    response = await client.post("/auth/magic-link", json={"email": "nobody@example.com"})
    assert response.status_code == 202
    async with api.app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0


async def test_a_sign_in_link_works_once(api):
    client = api.client()
    await client.post("/auth/magic-link", json={"email": "a@example.com"})
    token = parse_qs(urlparse(api.sender.sent[-1][1]).query)["token"][0]
    assert (await client.get("/auth/callback", params={"token": token})).status_code == 303
    assert (await client.get("/auth/callback", params={"token": token})).status_code == 400


async def test_an_expired_sign_in_link_is_refused(api):
    client = api.client()
    await client.post("/auth/magic-link", json={"email": "a@example.com"})
    token = parse_qs(urlparse(api.sender.sent[-1][1]).query)["token"][0]
    async with api.app.state.sessions() as db:
        await db.execute(update(LoginToken).values(expires_at=datetime.now(UTC) - timedelta(1)))
        await db.commit()
    assert (await client.get("/auth/callback", params={"token": token})).status_code == 400


async def test_only_hashes_of_tokens_are_stored(api):
    client = await api.signed_in("a@example.com")
    cookie = client.cookies["starboard_session"]
    async with api.app.state.sessions() as db:
        stored = await db.scalars(select(Session.token_hash))
        assert cookie not in stored.all()


async def test_signing_out_ends_the_session(api):
    client = await api.signed_in("a@example.com")
    cookie = client.cookies["starboard_session"]
    assert (await client.post("/auth/sign-out")).status_code == 204
    client.cookies.set("starboard_session", cookie)
    assert (await client.get("/me")).status_code == 401


async def test_an_expired_session_is_refused(api):
    client = await api.signed_in("a@example.com")
    async with api.app.state.sessions() as db:
        await db.execute(update(Session).values(expires_at=datetime.now(UTC) - timedelta(1)))
        await db.commit()
    assert (await client.get("/me")).status_code == 401


async def test_without_a_session_nothing_is_readable(api):
    assert (await api.client().get("/me")).status_code == 401


async def test_the_creator_owns_a_new_organization(api):
    client = await api.signed_in("owner@example.com")
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()
    me = (await client.get("/me")).json()
    assert me["organizations"] == [{"org_id": org["id"], "name": "Hauler", "role": "owner"}]
    assert (await client.get(f"/orgs/{org['id']}")).json()["name"] == "Hauler"


async def test_another_organization_is_not_found(api):
    alice = await api.signed_in("alice@example.com")
    bob = await api.signed_in("bob@example.com")
    org = (await alice.post("/orgs", json={"name": "Alice Hauling"})).json()
    for path in (f"/orgs/{org['id']}", f"/orgs/{org['id']}/members"):
        response = await bob.get(path)
        assert response.status_code == 404, path
    response = await bob.put(
        f"/orgs/{org['id']}/members", json={"email": "bob@example.com", "role": "owner"}
    )
    assert response.status_code == 404


async def test_an_owner_adds_members_and_a_viewer_cannot(api):
    owner = await api.signed_in("owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Hauler"})).json()
    added = await owner.put(
        f"/orgs/{org['id']}/members", json={"email": "Viewer@Example.com", "role": "viewer"}
    )
    assert added.status_code == 200
    viewer = await api.signed_in("viewer@example.com")
    members = (await viewer.get(f"/orgs/{org['id']}/members")).json()
    assert [(m["email"], m["role"]) for m in members] == [
        ("owner@example.com", "owner"),
        ("viewer@example.com", "viewer"),
    ]
    refused = await viewer.put(
        f"/orgs/{org['id']}/members", json={"email": "x@example.com", "role": "planner"}
    )
    assert refused.status_code == 403


async def test_the_last_owner_cannot_step_down(api):
    owner = await api.signed_in("owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Hauler"})).json()
    response = await owner.put(
        f"/orgs/{org['id']}/members", json={"email": "owner@example.com", "role": "viewer"}
    )
    assert response.status_code == 409
