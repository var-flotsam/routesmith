"""Alembic environment: migrations run on the async engine from the API settings."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from starboard.api.db import engine_for
from starboard.api.models import Base
from starboard.api.settings import Settings


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # PostGIS ships its own tables (spatial_ref_sys and the tiger and topology schemas).
    return not (type_ == "table" and reflected and compare_to is None)


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _migrate() -> None:
    engine = engine_for(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; set STARBOARD_DATABASE_URL")
asyncio.run(_migrate())
