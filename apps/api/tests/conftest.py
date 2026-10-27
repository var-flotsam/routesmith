"""Fixtures for API tests against a real PostGIS database.

Tests that take `api` need STARBOARD_TEST_DATABASE_URL (CI sets it); they are skipped
otherwise. The database is migrated once and emptied before each test.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import text

from starboard.api.app import create_app
from starboard.api.email import RecordingEmailSender
from starboard.api.models import Base
from starboard.api.queue import IMPORT_UPLOAD, SOLVE_RUN, RecordingQueue
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore
from starboard.geo.geocoding import (
    Address,
    FoundPlace,
    GeocodeOutcome,
    GeocodeQuality,
    GeocoderUnavailableError,
)
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.graph import StateGraph
from starboard.worker.jobs import Context, import_upload, solve_run

DATABASE_URL = os.environ.get("STARBOARD_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[3]


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "STARBOARD_DATABASE_URL": DATABASE_URL or ""}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def migrated() -> None:
    if DATABASE_URL is None:
        pytest.skip("STARBOARD_TEST_DATABASE_URL names no test database")
    result = alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr


GRID = Grid()


class FakeGeocoder:
    """Tests: addresses "x y" on the grid are found there; "maybe x y" is an inexact match;
    "twice" is ambiguous; anything else is not found. A one-line search finds the same,
    with two places for "twice", and "down" stands for the service not answering."""

    def find(self, address: str) -> list[FoundPlace]:
        if address == "down":
            raise GeocoderUnavailableError("the fake geocoder is down")
        if address == "twice":
            return [
                FoundPlace("1 TWICE ST, A", GRID.at(0, 0)),
                FoundPlace("1 TWICE ST, B", GRID.at(100, 0)),
            ]
        try:
            x, y = (float(part) for part in address.split(" "))
        except ValueError:
            return []
        return [FoundPlace(f"{address} on the grid", GRID.at(x, y))]

    def geocode(self, addresses: Sequence[Address]) -> list[GeocodeOutcome]:
        outcomes = []
        for address in addresses:
            text = address.street
            quality = GeocodeQuality.EXACT
            if text.startswith("maybe "):
                text, quality = text.removeprefix("maybe "), GeocodeQuality.INEXACT
            if text == "twice":
                outcomes.append(GeocodeOutcome(GeocodeQuality.AMBIGUOUS))
                continue
            try:
                x, y = (float(part) for part in text.split(" "))
            except ValueError:
                outcomes.append(GeocodeOutcome(GeocodeQuality.NOT_FOUND))
                continue
            outcomes.append(GeocodeOutcome(quality, GRID.at(x, y), f"{text} on the grid"))
        return outcomes


class Api:
    """The app, its recorded emails and jobs, and a signed-in client per user.

    `run_jobs` runs the queued worker jobs in-process, on the default synthetic grid.
    """

    def __init__(
        self, app: Any, sender: RecordingEmailSender, queue: RecordingQueue, geocoder: FakeGeocoder
    ) -> None:
        self.app = app
        self.sender = sender
        self.queue = queue
        self.clients: list[httpx.AsyncClient] = []
        self.network: Callable[[Any], StateGraph] = lambda bbox: build_state_graph(GRID.segments())
        self.geocoder = geocoder

    async def run_jobs(self) -> list[str]:
        context = Context(
            self.app.state.sessions, self.app.state.store, self.network, self.geocoder
        )
        jobs = {IMPORT_UPLOAD: import_upload, SOLVE_RUN: solve_run}
        outcomes = []
        while self.queue.jobs:
            name, row_id = self.queue.jobs.pop(0)
            outcomes.append(await jobs[name]({"starboard": context}, str(row_id)))
        return outcomes

    def client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        self.clients.append(client)
        return client

    async def signed_in(self, email: str) -> httpx.AsyncClient:
        client = self.client()
        response = await client.post("/auth/magic-link", json={"email": email})
        assert response.status_code == 202
        _, link = self.sender.sent[-1]
        token = parse_qs(urlparse(link).query)["token"][0]
        response = await client.get("/auth/callback", params={"token": token})
        assert response.status_code == 303, response.text
        return client


@pytest.fixture
async def api(migrated: None, tmp_path: Path) -> AsyncIterator[Api]:
    settings = Settings(database_url=DATABASE_URL or "", cookie_secure=False)
    sender, queue, geocoder = RecordingEmailSender(), RecordingQueue(), FakeGeocoder()
    app = create_app(settings, sender, LocalObjectStore(tmp_path / "uploads"), queue, geocoder)
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with app.state.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    harness = Api(app, sender, queue, geocoder)
    yield harness
    for client in harness.clients:
        await client.aclose()
    await app.state.engine.dispose()
