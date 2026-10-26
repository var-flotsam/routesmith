"""Share links: read-only, need no sign-in, replaced or taken away, and scoped by org."""

import pytest
from sqlalchemy import select

from starboard.api.models import ShareLink
from starboard.geo.synthetic import Grid

pytestmark = pytest.mark.anyio

GRID = Grid()  # the grid the test harness builds the network from


def _site(x, y):
    point = GRID.at(x, y)
    return {"lon": point.lon, "lat": point.lat}


async def _solved_run(api, email="planner@example.com"):
    client = await api.signed_in(email)
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    body = {"name": "Grid", "yard": _site(0, 0), "disposal": _site(0, 0), "capacity_carts": 2}
    route = (await client.post(f"/orgs/{org}/routes", json=body)).json()["id"]
    rows = ["stop_id,current_sequence,lon,lat"]
    for k, (x, y) in enumerate([(20, -10), (60, -10)], start=1):
        p = GRID.at(x, y)
        rows.append(f"s{k},{k},{p.lon},{p.lat}")
    files = {"file": ("stops.csv", ("\n".join(rows) + "\n").encode(), "text/csv")}
    upload = (await client.post(f"/orgs/{org}/routes/{route}/uploads", files=files)).json()
    await api.run_jobs()
    run = (
        await client.post(
            f"/orgs/{org}/routes/{route}/runs",
            json={"upload_id": upload["id"], "objective": "balanced-total"},
        )
    ).json()
    await api.run_jobs()
    return client, org, run["id"]


def _token(url):
    return url.rsplit("/shared/", 1)[1]


async def test_a_share_link_shows_the_result_to_someone_not_signed_in(api):
    client, org, run = await _solved_run(api)
    made = await client.put(f"/orgs/{org}/runs/{run}/share-link")
    assert made.status_code == 200
    url = made.json()["url"]
    assert url.startswith("http://localhost:5173/shared/")
    shared = await api.client().get(f"/shared/{_token(url)}")
    assert shared.status_code == 200
    body = shared.json()
    assert body["route_name"] == "Grid"
    assert body["report"]["optimized"]["area"]["stops_serviced"] == 2
    assert "org" not in str(body.keys())
    state = (await client.get(f"/orgs/{org}/runs/{run}/share-link")).json()
    assert state["shared"] is True


async def test_only_the_hash_of_a_link_is_stored(api):
    client, org, run = await _solved_run(api)
    url = (await client.put(f"/orgs/{org}/runs/{run}/share-link")).json()["url"]
    async with api.app.state.sessions() as db:
        assert _token(url) not in (await db.scalars(select(ShareLink.token_hash))).all()


async def test_a_new_link_replaces_the_old_one_and_stopping_ends_both(api):
    client, org, run = await _solved_run(api)
    first = _token((await client.put(f"/orgs/{org}/runs/{run}/share-link")).json()["url"])
    second = _token((await client.put(f"/orgs/{org}/runs/{run}/share-link")).json()["url"])
    stranger = api.client()
    assert (await stranger.get(f"/shared/{first}")).status_code == 404
    assert (await stranger.get(f"/shared/{second}")).status_code == 200
    assert (await client.delete(f"/orgs/{org}/runs/{run}/share-link")).status_code == 204
    assert (await stranger.get(f"/shared/{second}")).status_code == 404
    state = (await client.get(f"/orgs/{org}/runs/{run}/share-link")).json()
    assert state == {"shared": False, "created_at": None}


async def test_a_viewer_cannot_share(api):
    client, org, run = await _solved_run(api)
    await client.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    assert (await viewer.put(f"/orgs/{org}/runs/{run}/share-link")).status_code == 403
    assert (await viewer.get(f"/orgs/{org}/runs/{run}/share-link")).status_code == 200


async def test_another_organization_cannot_share_or_stop_sharing(api):
    alice, alice_org, run = await _solved_run(api, "alice@example.com")
    await alice.put(f"/orgs/{alice_org}/runs/{run}/share-link")
    bob = await api.signed_in("bob@example.com")
    bob_org = (await bob.post("/orgs", json={"name": "Bob Hauling"})).json()["id"]
    for org in (alice_org, bob_org):
        path = f"/orgs/{org}/runs/{run}/share-link"
        assert (await bob.put(path)).status_code == 404
        assert (await bob.get(path)).status_code == 404
        assert (await bob.delete(path)).status_code == 404
    assert (await alice.get(f"/orgs/{alice_org}/runs/{run}/share-link")).json()["shared"]


async def test_an_unknown_link_is_not_found(api):
    assert (await api.client().get("/shared/not-a-real-link")).status_code == 404
