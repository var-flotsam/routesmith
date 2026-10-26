"""The arq worker: `arq starboard.worker.main.WorkerSettings`.

It reads the same `STARBOARD_*` settings as the API, so both see one database,
one Redis and one file store.
"""

from functools import partial
from typing import Any, ClassVar

from arq.connections import RedisSettings

from starboard.api.db import engine_for, session_maker
from starboard.api.queue import IMPORT_UPLOAD
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore
from starboard.geo.osm import fetch_network
from starboard.worker.jobs import Context, import_upload

_settings = Settings()


async def _startup(ctx: dict[str, Any]) -> None:
    engine = engine_for(_settings.database_url)
    ctx["engine"] = engine
    ctx["starboard"] = Context(
        sessions=session_maker(engine),
        store=LocalObjectStore(_settings.upload_dir),
        network=partial(
            fetch_network, cache_dir=_settings.osm_cache_dir, extract=_settings.osm_extract
        ),
    )


async def _shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [import_upload]
    on_startup = _startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    # Building a network for a new area can take minutes the first time.
    job_timeout = 30 * 60


assert import_upload.__name__ == IMPORT_UPLOAD  # the API enqueues jobs by this name
