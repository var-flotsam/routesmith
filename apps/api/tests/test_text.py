"""Text the API refuses is a 422, never a server error, and text it stored reads back."""

import uuid

import pytest
from pydantic import ValidationError

from starboard.api.routers.auth import MagicLinkRequest
from starboard.api.routers.orgs import NewOrganization
from starboard.api.routers.routes import Location, RouteChanges, RouteOut
from starboard.geo.synthetic import Grid

NUL, TAB, ESCAPE, DELETE = chr(0), chr(9), chr(27), chr(127)
NEXT_LINE, NO_BREAK_SPACE, LINE_SEPARATOR = chr(0x85), chr(0xA0), chr(0x2028)
IDEOGRAPHIC_SPACE, BYTE_ORDER_MARK = chr(0x3000), chr(0xFEFF)
DOTTED_CAPITAL_I = chr(0x130)  # lower-cases to two characters


@pytest.mark.parametrize("control", [NUL, ESCAPE, DELETE])
def test_an_address_or_a_name_with_a_control_character_is_refused(control):
    with pytest.raises(ValidationError):
        MagicLinkRequest(email=f"{control}@0")
    with pytest.raises(ValidationError):
        NewOrganization(name=f"Hauler{control}")
    with pytest.raises(ValidationError):
        RouteChanges(name=f"Route{control}")


def test_ordinary_addresses_and_names_still_pass():
    assert MagicLinkRequest(email="planner@example.com").email == "planner@example.com"
    # U+02BB is the Hawaiian okina, escaped because it looks like a quote mark.
    name = "K\u0101ne\u02bbohe Hauling & Sons"
    assert NewOrganization(name=name).name == name


def test_names_lose_the_spaces_around_them_and_a_blank_name_is_refused():
    assert NewOrganization(name="  Hauler  ").name == "Hauler"
    for blank in ["   ", IDEOGRAPHIC_SPACE, NO_BREAK_SPACE]:
        with pytest.raises(ValidationError):
            NewOrganization(name=blank)
        with pytest.raises(ValidationError):
            RouteChanges(name=blank)


@pytest.mark.parametrize(
    "space", [" ", NEXT_LINE, NO_BREAK_SPACE, LINE_SEPARATOR, IDEOGRAPHIC_SPACE, BYTE_ORDER_MARK]
)
def test_an_address_with_any_kind_of_space_is_refused(space):
    # The published pattern refuses each of these too, so the spec and the server agree.
    with pytest.raises(ValidationError):
        MagicLinkRequest(email=f"plan{space}ner@example.com")


def test_an_address_too_long_once_in_lower_case_is_refused():
    assert MagicLinkRequest(email="a" * 160 + "@" + "b" * 159)
    with pytest.raises(ValidationError):
        MagicLinkRequest(email=DOTTED_CAPITAL_I * 160 + "@" + "b" * 159)


def test_a_stored_route_name_reads_back_whatever_it_holds():
    site = Location(lon=0, lat=0)
    route = RouteOut(id=uuid.uuid4(), name=f"Route{TAB}1", yard=site, disposal=site)
    assert route.name == f"Route{TAB}1"


@pytest.mark.anyio
async def test_a_nul_in_a_request_is_a_validation_error(api):
    client = await api.signed_in("planner@example.com")
    response = await client.post("/auth/magic-link", json={"email": NUL + "@0"})
    assert response.status_code == 422
    assert (await client.post("/orgs", json={"name": "a" + NUL})).status_code == 422
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    site = {"lon": 0, "lat": 0}
    route = {"name": " ", "yard": site, "disposal": site}
    assert (await client.post(f"/orgs/{org}/routes", json=route)).status_code == 422


@pytest.mark.anyio
async def test_a_stop_id_with_a_tab_can_be_reviewed_and_a_nul_is_refused(api):
    grid = Grid()  # the grid the test harness builds the network from
    client = await api.signed_in("planner@example.com")
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    yard = {"lon": grid.at(0, 0).lon, "lat": grid.at(0, 0).lat}
    route = {"name": "Grid", "yard": yard, "disposal": yard}
    route_id = (await client.post(f"/orgs/{org}/routes", json=route)).json()["id"]
    beside, mid_block = grid.at(20, -10), grid.at(50, 50)  # the second goes to review
    rows = [
        "stop_id,current_sequence,lon,lat",
        f"s1,1,{beside.lon},{beside.lat}",
        f"lot 4{TAB}rear,2,{mid_block.lon},{mid_block.lat}",
    ]
    files = {"file": ("stops.csv", ("\n".join(rows) + "\n").encode(), "text/csv")}
    upload = (await client.post(f"/orgs/{org}/routes/{route_id}/uploads", files=files)).json()
    await api.run_jobs()
    base = f"/orgs/{org}/uploads/{upload['id']}/stops"
    (item,) = (await client.get(f"{base}?state=review")).json()
    assert item["stop_id"] == f"lot 4{TAB}rear"
    placement = {"segment_id": "h-0-0", "curb_side": "right"}
    assert (await client.put(f"{base}/lot%204%00rear/placement", json=placement)).status_code == 422
    assert (await client.put(f"{base}/lot%204%00rear/exclusion")).status_code == 422
    assert (await client.put(f"{base}/lot%204%09rear/exclusion")).status_code == 200
