"""Finding a yard or disposal site by address, roles, the cross-org negative test, and a
route keeping the address each site was found by."""

import pytest

from starboard.geo.geocoding import CENSUS_ONELINE_MAX_CHARACTERS
from starboard.geo.synthetic import Grid

GRID = Grid()  # the grid the fake geocoder finds addresses on

pytestmark = pytest.mark.anyio


async def _org(client, name="Hauler"):
    return (await client.post("/orgs", json={"name": name})).json()["id"]


async def _find(client, org, address):
    return await client.get(f"/orgs/{org}/places", params={"address": address})


async def test_an_address_is_found_where_the_geocoder_puts_it(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    response = await _find(planner, org, "  10   20 ")
    assert response.status_code == 200
    point = GRID.at(10, 20)
    assert response.json() == [{"lon": point.lon, "lat": point.lat, "address": "10 20 on the grid"}]


async def test_every_place_an_address_could_be_is_listed_or_none(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    twice = (await _find(planner, org, "twice")).json()
    assert [place["address"] for place in twice] == ["1 TWICE ST, A", "1 TWICE ST, B"]
    assert (await _find(planner, org, "nowhere at all")).json() == []


async def test_lat_lon_is_taken_as_that_point(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    found = (await _find(planner, org, "41.0171, -73.6463")).json()
    assert found == [{"lon": -73.6463, "lat": 41.0171, "address": None}]
    # Out of range as lat, lon: an address, which the geocoder does not know.
    assert (await _find(planner, org, "-120.5, 41.0")).json() == []


async def test_a_geocoder_that_does_not_answer_is_a_502(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    assert (await _find(planner, org, "down")).status_code == 502


async def test_an_address_with_a_control_character_is_refused(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    assert (await _find(planner, org, "1 Main St" + chr(0))).status_code == 422
    assert (await _find(planner, org, "")).status_code == 422
    assert (await _find(planner, org, "   ")).status_code == 422


async def test_an_address_longer_than_the_geocoder_takes_is_refused(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    longest = "1 Main St, " + "x" * (CENSUS_ONELINE_MAX_CHARACTERS - len("1 Main St, "))
    assert (await _find(planner, org, longest)).status_code == 200
    assert (await _find(planner, org, longest + "x")).status_code == 422


async def test_a_viewer_cannot_look_up_places_and_another_org_is_not_found(api):
    owner = await api.signed_in("owner@example.com")
    org = await _org(owner)
    await owner.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    assert (await _find(viewer, org, "10 20")).status_code == 403
    outsider = await api.signed_in("outsider@example.com")
    await _org(outsider, "Other hauler")
    assert (await _find(outsider, org, "10 20")).status_code == 404


async def test_a_route_keeps_the_address_each_site_was_found_by(api):
    planner = await api.signed_in("planner@example.com")
    org = await _org(planner)
    (yard,) = (await _find(planner, org, "10 20")).json()
    (disposal,) = (await _find(planner, org, "41.0171, -73.6463")).json()
    route = {"name": "Grid", "yard": yard, "disposal": disposal}
    created = (await planner.post(f"/orgs/{org}/routes", json=route)).json()
    assert created["yard"] == yard and created["disposal"] == disposal
    moved = {"lon": 1.0, "lat": 2.0}
    changed = await planner.patch(f"/orgs/{org}/routes/{created['id']}", json={"yard": moved})
    assert changed.json()["yard"] == {**moved, "address": None}
    assert changed.json()["disposal"] == disposal
