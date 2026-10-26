"""Handing work to the worker. Jobs carry ids only; the worker reads the rest itself."""

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

IMPORT_UPLOAD = "import_upload"
SOLVE_RUN = "solve_run"


class JobQueue(Protocol):
    async def enqueue(self, job: str, row_id: uuid.UUID) -> None: ...


class ArqQueue:
    """The Redis queue the arq worker reads; connects on first use."""

    def __init__(self, redis_url: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def enqueue(self, job: str, row_id: uuid.UUID) -> None:
        if self._pool is None:
            self._pool = await create_pool(self._settings)
        await self._pool.enqueue_job(job, str(row_id))


@dataclass
class RecordingQueue:
    """Tests: keeps every job it is asked to enqueue."""

    jobs: list[tuple[str, uuid.UUID]] = field(default_factory=list)

    async def enqueue(self, job: str, row_id: uuid.UUID) -> None:
        self.jobs.append((job, row_id))
