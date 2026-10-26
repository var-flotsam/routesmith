"""Routes: create, read, change, roles, and the cross-org negative tests."""

import pytest

pytestmark = pytest.mark.anyio

BYRAM = {
    "name": "Byram",
    "yard": {"lon": -73.6462628, "lat": 41.0171437},
    "disposal": {"lon": -73.6462628, "lat": 41.0171437},
    "capacity_carts": 420,
}


async def _org(client, name="Hauler"):
    return (await client.post("/orgs", json={"name": name})).json()["id"]


async def test_a_planner_creates_and_reads_a_route(api):
    owner = await api.signed_in("owner@example.com")
    org = await _org(owner)
    created = await owner.post(f"/orgs/{org}/routes", json=BYRAM)
    assert created.status_code == 201
    route = created.json()
    assert route["yard"] == pytest.approx(BYRAM["yard"])
    assert route["capacity_carts"] == 420
    assert route["max_route_hours"] is None
    read = (await owner.get(f"/orgs/{org}/routes/{route['id']}")).json()
    assert read == route
    assert (await owner.get(f"/orgs/{org}/routes")).json() == [route]


async def test_a_change_touches_only_the_fields_given(api):
    owner = await api.signed_in("owner@example.com")
    org = await _org(owner)
    route = (await owner.post(f"/orgs/{org}/routes", json=BYRAM)).json()
    changed = await owner.patch(
        f"/orgs/{org}/routes/{route['id']}", json={"max_route_hours": 7.5, "capacity_carts": None}
    )
    assert changed.status_code == 200
    body = changed.json()
    assert body["max_route_hours"] == 7.5
    assert body["capacity_carts"] is None
    assert body["name"] == "Byram"


async def test_a_viewer_reads_routes_but_cannot_create_or_change_them(api):
    owner = await api.signed_in("owner@example.com")
    org = await _org(owner)
    route = (await owner.post(f"/orgs/{org}/routes", json=BYRAM)).json()
    await owner.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    assert (await viewer.get(f"/orgs/{org}/routes/{route['id']}")).status_code == 200
    assert (await viewer.post(f"/orgs/{org}/routes", json=BYRAM)).status_code == 403
    response = await viewer.patch(f"/orgs/{org}/routes/{route['id']}", json={"name": "X"})
    assert response.status_code == 403


async def test_another_organizations_routes_are_not_found(api):
    alice = await api.signed_in("alice@example.com")
    bob = await api.signed_in("bob@example.com")
    alice_org = await _org(alice, "Alice Hauling")
    bob_org = await _org(bob, "Bob Hauling")
    route = (await alice.post(f"/orgs/{alice_org}/routes", json=BYRAM)).json()
    # Bob, through Alice's organization: not a member.
    assert (await bob.get(f"/orgs/{alice_org}/routes")).status_code == 404
    assert (await bob.get(f"/orgs/{alice_org}/routes/{route['id']}")).status_code == 404
    # Bob, through his own organization, naming Alice's route.
    assert (await bob.get(f"/orgs/{bob_org}/routes/{route['id']}")).status_code == 404
    response = await bob.patch(f"/orgs/{bob_org}/routes/{route['id']}", json={"name": "Mine"})
    assert response.status_code == 404
    assert (await bob.get(f"/orgs/{bob_org}/routes")).json() == []
    assert (await alice.get(f"/orgs/{alice_org}/routes/{route['id']}")).json()["name"] == "Byram"


async def test_a_location_off_the_globe_is_refused(api):
    owner = await api.signed_in("owner@example.com")
    org = await _org(owner)
    bad = {**BYRAM, "yard": {"lon": -273.0, "lat": 41.0}}
    assert (await owner.post(f"/orgs/{org}/routes", json=bad)).status_code == 422
