"""Stop uploads: stored, queued, read and snapped by the worker, and scoped by org."""

import pytest

from starboard.geo.synthetic import Grid

GRID = Grid()  # the grid the test harness builds the network from

pytestmark = pytest.mark.anyio


def _route(yard=(0, 0)):
    point = GRID.at(*yard)
    site = {"lon": point.lon, "lat": point.lat}
    return {"name": "Grid", "yard": site, "disposal": site, "capacity_carts": 2}


def _csv(*, with_routes=False):
    header = "stop_id,current_sequence,lon,lat" + (",route_id" if with_routes else "")
    rows = [header]
    # Four stops beside streets, then one in the middle of a block, then a bad row.
    points = [(20, -10), (60, -10), (110, 50), (150, 90), (50, 50)]
    for index, (x, y) in enumerate(points, start=1):
        p = GRID.at(x, y)
        route = ",A" if with_routes else ""
        rows.append(f"s{index},{index},{p.lon},{p.lat}{route}")
    rows.append("bad,9,not-a-number,41" + (",A" if with_routes else ""))
    return ("\n".join(rows) + "\n").encode()


async def _setup(api, email="planner@example.com"):
    client = await api.signed_in(email)
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    route = (await client.post(f"/orgs/{org}/routes", json=_route())).json()["id"]
    return client, org, route


async def _upload(client, org, route, body=None):
    files = {"file": ("stops.csv", body or _csv(), "text/csv")}
    return await client.post(f"/orgs/{org}/routes/{route}/uploads", files=files)


async def test_an_upload_is_queued_then_snapped_by_the_worker(api):
    client, org, route = await _setup(api)
    response = await _upload(client, org, route)
    assert response.status_code == 202
    upload = response.json()
    assert upload["state"] == "processing"
    assert [job for job, _ in api.queue.jobs] == ["import_upload"]
    assert await api.run_jobs() == ["ready"]
    done = (await client.get(f"/orgs/{org}/uploads/{upload['id']}")).json()
    assert done["state"] == "ready"
    assert done["rows_read"] == 6
    assert done["rows_rejected"] == 1
    assert done["rejected_rows"] == [
        {"line": 7, "reason": "current_sequence, lon or lat is not a number"}
    ]
    assert done["stops_snapped"] == 4
    assert done["stops_in_review"] == 1


async def test_the_review_queue_lists_stops_the_planner_must_place(api):
    client, org, route = await _setup(api)
    upload = (await _upload(client, org, route)).json()
    await api.run_jobs()
    review = (await client.get(f"/orgs/{org}/uploads/{upload['id']}/stops?state=review")).json()
    assert [(s["stop_id"], s["review_reason"]) for s in review] == [("s5", "outside_network")]
    every = (await client.get(f"/orgs/{org}/uploads/{upload['id']}/stops")).json()
    assert [s["stop_id"] for s in every] == ["s1", "s2", "s3", "s4", "s5"]
    snapped = every[0]
    assert snapped["state"] == "snapped" and snapped["segment_id"] and snapped["curb_side"]


async def test_route_ids_in_the_file_are_kept(api):
    client, org, route = await _setup(api)
    upload = (await _upload(client, org, route, _csv(with_routes=True))).json()
    await api.run_jobs()
    stops = (await client.get(f"/orgs/{org}/uploads/{upload['id']}/stops")).json()
    assert {s["current_route_id"] for s in stops} == {"A"}


async def test_a_failure_while_snapping_marks_the_upload_failed(api):
    client, org, route = await _setup(api)
    upload = (await _upload(client, org, route)).json()

    def unreachable(bbox):
        raise ConnectionError("the street network could not be fetched")

    api.network = unreachable
    assert await api.run_jobs() == ["failed"]
    failed = (await client.get(f"/orgs/{org}/uploads/{upload['id']}")).json()
    assert failed["state"] == "failed"
    assert "could not be fetched" in failed["failure_reason"]


async def test_a_viewer_cannot_upload(api):
    client, org, route = await _setup(api)
    await client.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    assert (await _upload(viewer, org, route)).status_code == 403


async def test_another_organizations_uploads_are_not_found(api):
    alice, alice_org, alice_route = await _setup(api, "alice@example.com")
    bob, bob_org, bob_route = await _setup(api, "bob@example.com")
    upload = (await _upload(alice, alice_org, alice_route)).json()
    await api.run_jobs()
    for path in (
        f"/orgs/{alice_org}/uploads/{upload['id']}",
        f"/orgs/{bob_org}/uploads/{upload['id']}",
        f"/orgs/{bob_org}/uploads/{upload['id']}/stops",
        f"/orgs/{alice_org}/routes/{alice_route}/uploads",
        f"/orgs/{bob_org}/routes/{alice_route}/uploads",
    ):
        assert (await bob.get(path)).status_code == 404, path
    assert (await _upload(bob, bob_org, alice_route)).status_code == 404
    assert (await bob.get(f"/orgs/{bob_org}/routes/{bob_route}/uploads")).json() == []
