"""The demo seed: a ready-to-try organization, route and stop list for one email."""

import pytest
from sqlalchemy import func, select

from starboard.api.demo import DEMO_ROUTE, seed_demo
from starboard.api.models import Route, Upload

pytestmark = pytest.mark.anyio


async def test_the_demo_is_seeded_once_and_shows_up_after_sign_in(api):
    state = api.app.state
    first = await seed_demo(state.sessions, state.store, api.queue, "Planner@Example.com")
    again = await seed_demo(state.sessions, state.store, api.queue, "planner@example.com")
    assert (again.org_id, again.route_id) == (first.org_id, first.route_id)
    assert first.upload_id is not None and again.upload_id is None
    assert [job for job, _ in api.queue.jobs] == ["import_upload"]
    async with state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Upload)) == 1
        route = await db.get(Route, first.route_id)
        assert route is not None and route.capacity_carts == 420

    client = await api.signed_in("planner@example.com")
    routes = (await client.get(f"/orgs/{first.org_id}/routes")).json()
    assert [r["name"] for r in routes] == [DEMO_ROUTE]
    assert await api.run_jobs() == ["ready"]
    upload = (await client.get(f"/orgs/{first.org_id}/uploads/{first.upload_id}")).json()
    assert upload["rows_read"] == 754
