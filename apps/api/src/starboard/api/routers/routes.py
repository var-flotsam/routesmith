"""Routes: a name, the truck profile, and the yard and disposal site."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from pydantic import BaseModel, Field
from shapely.geometry import Point

from starboard.api.deps import IN_ORG, Database, member
from starboard.api.models import Membership, Role, Route
from starboard.api.scoping import in_org, one_in_org
from starboard.api.text import Name

router = APIRouter(tags=["routes"], responses=IN_ORG)

Viewer = Annotated[Membership, Depends(member(Role.VIEWER))]
Planner = Annotated[Membership, Depends(member(Role.PLANNER))]


class Location(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class RouteFields(BaseModel):
    name: Name
    yard: Location
    disposal: Location
    capacity_carts: int | None = Field(default=None, ge=1, description="carts per load")
    max_route_hours: float | None = Field(default=None, gt=0, description="longest route")


class RouteChanges(BaseModel):
    name: Name | None = None
    yard: Location | None = None
    disposal: Location | None = None
    capacity_carts: int | None = Field(default=None, ge=1)
    max_route_hours: float | None = Field(default=None, gt=0)


class RouteOut(RouteFields):
    id: uuid.UUID
    name: str  # as stored; `Name` judges a name when it is set


def _point(location: Location) -> WKBElement:
    return from_shape(Point(location.lon, location.lat), srid=4326)


def _location(value: WKBElement) -> Location:
    shape = to_shape(value)
    assert isinstance(shape, Point)
    return Location(lon=shape.x, lat=shape.y)


def _out(route: Route) -> RouteOut:
    return RouteOut(
        id=route.id,
        name=route.name,
        yard=_location(route.yard),
        disposal=_location(route.disposal),
        capacity_carts=route.capacity_carts,
        max_route_hours=route.max_route_hours,
    )


@router.post("/orgs/{org_id}/routes", status_code=status.HTTP_201_CREATED)
async def create_route(org_id: uuid.UUID, body: RouteFields, db: Database, _: Planner) -> RouteOut:
    route = Route(
        org_id=org_id,
        name=body.name,
        yard=_point(body.yard),
        disposal=_point(body.disposal),
        capacity_carts=body.capacity_carts,
        max_route_hours=body.max_route_hours,
    )
    db.add(route)
    await db.commit()
    return _out(await one_in_org(db, Route, org_id, route.id))


@router.get("/orgs/{org_id}/routes")
async def list_routes(org_id: uuid.UUID, db: Database, _: Viewer) -> list[RouteOut]:
    routes = await db.scalars(in_org(Route, org_id).order_by(Route.name, Route.id))
    return [_out(r) for r in routes]


@router.get("/orgs/{org_id}/routes/{route_id}")
async def read_route(org_id: uuid.UUID, route_id: uuid.UUID, db: Database, _: Viewer) -> RouteOut:
    return _out(await one_in_org(db, Route, org_id, route_id))


@router.patch("/orgs/{org_id}/routes/{route_id}")
async def change_route(
    org_id: uuid.UUID, route_id: uuid.UUID, body: RouteChanges, db: Database, _: Planner
) -> RouteOut:
    """Change the fields given; send null for capacity or hours to remove the limit."""
    route = await one_in_org(db, Route, org_id, route_id)
    given = body.model_fields_set
    if body.name is not None:
        route.name = body.name
    if body.yard is not None:
        route.yard = _point(body.yard)
    if body.disposal is not None:
        route.disposal = _point(body.disposal)
    if "capacity_carts" in given:
        route.capacity_carts = body.capacity_carts
    if "max_route_hours" in given:
        route.max_route_hours = body.max_route_hours
    await db.commit()
    return _out(await one_in_org(db, Route, org_id, route_id))
