"""Control characters in text the API takes in are a 422, never a server error."""

import pytest
from pydantic import ValidationError

from starboard.api.routers.auth import MagicLinkRequest
from starboard.api.routers.orgs import NewOrganization
from starboard.api.routers.routes import RouteChanges

NUL, ESCAPE, DELETE = chr(0), chr(27), chr(127)


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
    assert NewOrganization(name="Kāneʻohe Hauling & Sons").name == "Kāneʻohe Hauling & Sons"


@pytest.mark.anyio
async def test_a_nul_in_a_request_is_a_validation_error(api):
    client = await api.signed_in("planner@example.com")
    response = await client.post("/auth/magic-link", json={"email": NUL + "@0"})
    assert response.status_code == 422
    assert (await client.post("/orgs", json={"name": "a" + NUL})).status_code == 422
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    path = f"/orgs/{org}/uploads/00000000-0000-0000-0000-000000000000/stops/s%001/exclusion"
    assert (await client.put(path)).status_code == 422
