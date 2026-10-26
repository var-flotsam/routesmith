"""Fixtures for API tests against a real PostGIS database.

Tests that take `api` need STARBOARD_TEST_DATABASE_URL (CI sets it); they are skipped
otherwise. The database is migrated once and emptied before each test.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import text

from starboard.api.app import create_app
from starboard.api.email import RecordingEmailSender
from starboard.api.models import Base
from starboard.api.settings import Settings

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


class Api:
    """The app, its recorded emails, and a way to get a signed-in client per user."""

    def __init__(self, app: Any, sender: RecordingEmailSender) -> None:
        self.app = app
        self.sender = sender
        self.clients: list[httpx.AsyncClient] = []

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
async def api(migrated: None) -> AsyncIterator[Api]:
    settings = Settings(database_url=DATABASE_URL or "", cookie_secure=False)
    sender = RecordingEmailSender()
    app = create_app(settings, sender)
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with app.state.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    harness = Api(app, sender)
    yield harness
    for client in harness.clients:
        await client.aclose()
    await app.state.engine.dispose()
