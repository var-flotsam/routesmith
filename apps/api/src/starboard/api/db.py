"""The async database engine."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def engine_for(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
