"""Preload the demo route for a user: `uv run python -m starboard.api.demo you@example.com`.

Creates (or reuses) the user, an organization "Demo" they own, the Byram route from
`data/demo/route.json`, and an upload of `data/demo/stops.csv` queued for the worker.
Sign in with that email afterwards. Running it again adds nothing already there.
"""

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from starboard.api.db import engine_for, session_maker
from starboard.api.models import Membership, Organization, Role, Route, Upload, UploadState, User
from starboard.api.queue import IMPORT_UPLOAD, ArqQueue, JobQueue
from starboard.api.security import normalized_email
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore, ObjectStore

DEMO_DIR = Path(__file__).resolve().parents[5] / "data" / "demo"
DEMO_ORGANIZATION = "Demo"
DEMO_ROUTE = "Byram (demo)"


@dataclass(frozen=True, slots=True)
class Seeded:
    org_id: uuid.UUID
    route_id: uuid.UUID
    upload_id: uuid.UUID | None  # None when the demo upload was already there


async def seed_demo(
    sessions: async_sessionmaker[AsyncSession],
    store: ObjectStore,
    queue: JobQueue,
    email: str,
    demo_dir: Path = DEMO_DIR,
) -> Seeded:
    address = normalized_email(email)
    config = json.loads((demo_dir / "route.json").read_text(encoding="utf-8"))
    async with sessions() as db:
        user = await db.scalar(select(User).where(User.email == address))
        if user is None:
            user = User(email=address)
            db.add(user)
            await db.flush()
        org = await db.scalar(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user.id, Organization.name == DEMO_ORGANIZATION)
        )
        if org is None:
            org = Organization(name=DEMO_ORGANIZATION)
            db.add(org)
            await db.flush()
            db.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER))
        route = await db.scalar(
            select(Route).where(Route.org_id == org.id, Route.name == DEMO_ROUTE)
        )
        if route is None:
            route = Route(
                org_id=org.id,
                name=DEMO_ROUTE,
                yard=from_shape(Point(config["yard"]["lon"], config["yard"]["lat"]), srid=4326),
                disposal=from_shape(
                    Point(config["disposal"]["lon"], config["disposal"]["lat"]), srid=4326
                ),
                capacity_carts=config.get("capacity_carts"),
                max_route_hours=config.get("max_route_hours"),
            )
            db.add(route)
            await db.flush()
        upload_id = None
        if await db.scalar(select(Upload.id).where(Upload.route_id == route.id)) is None:
            upload_id = uuid.uuid4()
            key = f"{org.id}/uploads/{upload_id}.csv"
            await store.put(key, (demo_dir / "stops.csv").read_bytes())
            db.add(
                Upload(
                    id=upload_id,
                    org_id=org.id,
                    route_id=route.id,
                    file_name="stops.csv",
                    object_key=key,
                    state=UploadState.PROCESSING,
                    rows_read=0,
                    rows_rejected=0,
                    rejected_rows=[],
                )
            )
        await db.commit()
        seeded = Seeded(org.id, route.id, upload_id)
    if upload_id is not None:
        await queue.enqueue(IMPORT_UPLOAD, upload_id)
    return seeded


async def _main(email: str) -> None:
    settings = Settings()
    engine = engine_for(settings.database_url)
    try:
        seeded = await seed_demo(
            session_maker(engine),
            LocalObjectStore(settings.upload_dir),
            ArqQueue(settings.redis_url),
            email,
        )
    finally:
        await engine.dispose()
    print(f"Demo route ready for {email}: organization {seeded.org_id}, route {seeded.route_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:  # the command and one email address
        raise SystemExit("usage: python -m starboard.api.demo you@example.com")
    asyncio.run(_main(sys.argv[1]))
