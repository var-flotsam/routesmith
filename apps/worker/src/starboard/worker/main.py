"""The arq worker: `arq starboard.worker.main.WorkerSettings`.

It reads the same `STARBOARD_*` settings as the API, so both see one database,
one Redis and one file store. Solves run in a process pool, so a long solve
does not stall the worker's event loop.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any, ClassVar

from arq.connections import RedisSettings

from starboard.api.db import engine_for, session_maker
from starboard.api.queue import IMPORT_UPLOAD, SOLVE_RUN
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore
from starboard.geo.geocoding import CensusGeocoder
from starboard.geo.osm import fetch_network
from starboard.worker.jobs import Context, import_upload, solve_run

_settings = Settings()


async def _startup(ctx: dict[str, Any]) -> None:
    engine = engine_for(_settings.database_url)
    pool = ProcessPoolExecutor()
    loop = asyncio.get_running_loop()

    async def in_pool(function: Callable[..., Any], *args: Any) -> Any:  # noqa: ANN401  # any solver entry point
        return await loop.run_in_executor(pool, function, *args)

    ctx["engine"], ctx["pool"] = engine, pool
    ctx["starboard"] = Context(
        sessions=session_maker(engine),
        store=LocalObjectStore(_settings.upload_dir),
        network=partial(
            fetch_network, cache_dir=_settings.osm_cache_dir, extract=_settings.osm_extract
        ),
        geocoder=CensusGeocoder(_settings.geocode_cache_dir),
        run_blocking=in_pool,
    )


async def _shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()
    ctx["pool"].shutdown()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [import_upload, solve_run]
    on_startup = _startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    # A ten-truck area solves in under an hour (ADR-0003 benchmark); a new area's network
    # can take minutes more to build.
    job_timeout = 2 * 60 * 60


# The API enqueues jobs by these names.
assert (import_upload.__name__, solve_run.__name__) == (IMPORT_UPLOAD, SOLVE_RUN)
