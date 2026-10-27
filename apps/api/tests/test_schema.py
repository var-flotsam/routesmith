"""schemathesis against the published OpenAPI spec: generated requests to every operation.

Each request is sent as a signed-in owner, with any `org_id` in the path pointed at
the owner's organization, so the generated bodies reach the handlers rather than
stopping at sign-in. Every answer must be one the spec lists, in the shape it gives,
and never a server error. Needs the test database, like the other API tests.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import Case
from schemathesis.specs.openapi.checks import positive_data_acceptance

from starboard.api.app import create_app
from starboard.api.db import engine_for, session_maker
from starboard.api.email import RecordingEmailSender
from starboard.api.models import Membership, Organization, Role, Session, User
from starboard.api.queue import RecordingQueue
from starboard.api.security import new_token, token_hash
from starboard.api.settings import Settings
from starboard.api.storage import LocalObjectStore
from starboard.geo.geocoding import FoundPlace

DATABASE_URL = os.environ.get("STARBOARD_TEST_DATABASE_URL")


class _NoPlaces:
    """An address finder that finds nothing, so no generated request reaches the Census."""

    def find(self, address: str) -> list[FoundPlace]:
        return []


async def _owner() -> tuple[str, uuid.UUID]:
    """A signed-in owner of a fresh organization: their session token and the org id."""
    engine = engine_for(DATABASE_URL or "")
    token = new_token()
    async with session_maker(engine)() as db:
        user = User(email=f"{uuid.uuid4()}@example.com")
        org = Organization(name="Fuzzed")
        db.add_all([user, org])
        await db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role=Role.OWNER))
        expires = datetime.now(UTC) + timedelta(hours=1)
        db.add(Session(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
        await db.commit()
        org_id = org.id
    await engine.dispose()
    return token, org_id


@pytest.fixture
def owner(migrated: None) -> tuple[str, uuid.UUID]:
    return asyncio.run(_owner())


@pytest.fixture
def api_schema(migrated: None, tmp_path: Path) -> schemathesis.BaseSchema:
    app = create_app(
        Settings(database_url=DATABASE_URL or "", cookie_secure=False),
        RecordingEmailSender(),
        LocalObjectStore(tmp_path / "uploads"),
        RecordingQueue(),
        _NoPlaces(),
    )
    return schemathesis.openapi.from_asgi("/openapi.json", app)


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_every_operation_answers_as_the_spec_says(case: Case, owner: tuple[str, uuid.UUID]) -> None:
    token, org_id = owner
    if case.path_parameters and "org_id" in case.path_parameters:
        case.path_parameters["org_id"] = str(org_id)
    excluded = []
    if case.path == "/auth/callback":
        # Any well-formed token is schema-valid, but only a real, unused link signs in.
        excluded.append(positive_data_acceptance)
    case.call_and_validate(cookies={"starboard_session": token}, excluded_checks=excluded)
