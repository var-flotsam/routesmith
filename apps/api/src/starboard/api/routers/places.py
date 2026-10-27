"""Finding a route's yard or disposal site by its address (HANDOFF §2.1, step 2).

The planner types an address; the geocoder lists every place it could be, and the
planner picks one, which the route then keeps with the address it was matched as. A
site with no street address the geocoder knows can be given as "lat, lon" instead.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from starboard.api.deps import IN_ORG, member
from starboard.api.models import Membership, Role
from starboard.api.text import ADDRESS_QUERY
from starboard.geo.geocoding import AddressFinder, GeocoderUnavailableError

router = APIRouter(
    tags=["places"],
    responses={**IN_ORG, 502: {"description": "the geocoder did not answer; try again"}},
)

Planner = Annotated[Membership, Depends(member(Role.PLANNER))]

# Latitude, then longitude, as map apps copy a point: "41.0171, -73.6463".
_LAT_LON = re.compile(r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*")
_MAX_LAT, _MAX_LON = 90, 180


class PlaceOut(BaseModel):
    lon: float
    lat: float
    address: str | None  # as the geocoder matched it; none for a place given by lat, lon


def _given_as_lat_lon(text: str) -> PlaceOut | None:
    match = _LAT_LON.fullmatch(text)
    if match is None:
        return None
    lat, lon = float(match[1]), float(match[2])
    if abs(lat) > _MAX_LAT or abs(lon) > _MAX_LON:
        return None
    return PlaceOut(lon=lon, lat=lat, address=None)


@router.get("/orgs/{org_id}/places")
async def find_places(
    org_id: uuid.UUID,
    address: Annotated[str, ADDRESS_QUERY],
    request: Request,
    _: Planner,
) -> list[PlaceOut]:
    """Every place an address could be, best first; an empty list if it names none.

    "lat, lon" is taken as that point. The geocoder covers the United States.
    """
    given = _given_as_lat_lon(address)
    if given is not None:
        return [given]
    line = " ".join(address.split())
    finder: AddressFinder = request.app.state.address_finder
    try:
        places = await run_in_threadpool(finder.find, line)
    except GeocoderUnavailableError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "the geocoder did not answer") from error
    return [PlaceOut(lon=p.location.lon, lat=p.location.lat, address=p.address) for p in places]
