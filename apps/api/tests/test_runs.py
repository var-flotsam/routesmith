"""Runs: started only on a cleared upload, solved by the worker, results scoped by org."""

import pytest

from starboard.geo.synthetic import Grid

pytestmark = pytest.mark.anyio

GRID = Grid()  # the grid the test harness builds the network from


def _site(x, y):
    point = GRID.at(x, y)
    return {"lon": point.lon, "lat": point.lat}


ROUTE = {"name": "Grid", "yard": _site(0, 0), "disposal": _site(0, 0), "capacity_carts": 2}


def _csv(points, routes=None):
    rows = ["stop_id,current_sequence,lon,lat" + (",route_id" if routes else "")]
    for index, (x, y) in enumerate(points, start=1):
        p = GRID.at(x, y)
        route = f",{routes[index - 1]}" if routes else ""
        rows.append(f"s{index},{index},{p.lon},{p.lat}{route}")
    return ("\n".join(rows) + "\n").encode()


BESIDE_STREETS = [(20, -10), (60, -10), (110, 50), (150, 90)]


async def _ready_upload(api, points=BESIDE_STREETS, routes=None, email="planner@example.com"):
    client = await api.signed_in(email)
    org = (await client.post("/orgs", json={"name": "Hauler"})).json()["id"]
    route = (await client.post(f"/orgs/{org}/routes", json=ROUTE)).json()["id"]
    files = {"file": ("stops.csv", _csv(points, routes), "text/csv")}
    upload = (await client.post(f"/orgs/{org}/routes/{route}/uploads", files=files)).json()
    await api.run_jobs()
    return client, org, route, upload["id"]


async def test_a_run_solves_the_upload_and_reports_current_against_optimized(api):
    client, org, route, upload = await _ready_upload(api)
    response = await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload})
    assert response.status_code == 202
    run = response.json()
    assert (run["state"], run["trucks"]) == ("queued", 1)
    assert await api.run_jobs() == ["succeeded"]
    done = (await client.get(f"/orgs/{org}/runs/{run['id']}")).json()
    assert done["state"] == "succeeded"
    assert done["solver_version"] and done["finished_at"]
    result = (await client.get(f"/orgs/{org}/runs/{run['id']}/result")).json()
    assert result["current"]["area"]["stops_serviced"] == 4
    assert result["optimized"]["area"]["stops_serviced"] == 4
    assert result["optimized"]["area"]["wrong_side_pickups"] == 0
    (optimized,) = result["optimized"]["routes"]
    assert sorted(optimized["order"]) == ["s1", "s2", "s3", "s4"]
    assert result["unserved"] == []
    listed = (await client.get(f"/orgs/{org}/routes/{route}/runs")).json()
    assert [r["id"] for r in listed] == [run["id"]]


async def test_current_route_ids_set_the_truck_count(api):
    client, org, route, upload = await _ready_upload(api, routes=["A", "A", "B", "B"])
    run = (await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload})).json()
    assert run["trucks"] == 2
    await api.run_jobs()
    result = (await client.get(f"/orgs/{org}/runs/{run['id']}/result")).json()
    assert [r["route_id"] for r in result["current"]["routes"]] == ["A", "B"]
    assert len(result["optimized"]["routes"]) == 2


async def test_a_placed_review_stop_is_solved_where_the_planner_put_it(api):
    client, org, route, upload = await _ready_upload(api, points=[*BESIDE_STREETS, (50, 50)])
    base = f"/orgs/{org}/uploads/{upload}"
    (item,) = (await client.get(f"{base}/stops?state=review")).json()
    start = await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload})
    assert start.status_code == 409  # nothing proceeds with stops in review
    await client.put(
        f"{base}/stops/{item['stop_id']}/placement",
        json={"segment_id": item["candidate_segment_ids"][0], "curb_side": "right"},
    )
    run = (await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload})).json()
    assert await api.run_jobs() == ["succeeded"]
    result = (await client.get(f"/orgs/{org}/runs/{run['id']}/result")).json()
    assert result["optimized"]["area"]["stops_serviced"] == 5


async def test_the_total_objective_needs_a_maximum_route_time(api):
    client, org, route, upload = await _ready_upload(api)
    body = {"upload_id": upload, "objective": "total"}
    response = await client.post(f"/orgs/{org}/routes/{route}/runs", json=body)
    assert response.status_code == 409


async def test_a_failed_solve_is_recorded_with_its_reason(api):
    client, org, route, upload = await _ready_upload(api)
    run = (await client.post(f"/orgs/{org}/routes/{route}/runs", json={"upload_id": upload})).json()

    def unreachable(bbox):
        raise ConnectionError("the street network could not be fetched")

    api.network = unreachable
    assert await api.run_jobs() == ["failed"]
    failed = (await client.get(f"/orgs/{org}/runs/{run['id']}")).json()
    assert "could not be fetched" in failed["failure_reason"]
    assert (await client.get(f"/orgs/{org}/runs/{run['id']}/result")).status_code == 404


async def test_a_viewer_reads_runs_but_cannot_start_one(api):
    client, org, route, upload = await _ready_upload(api)
    await client.put(f"/orgs/{org}/members", json={"email": "v@example.com", "role": "viewer"})
    viewer = await api.signed_in("v@example.com")
    body = {"upload_id": upload}
    assert (await viewer.post(f"/orgs/{org}/routes/{route}/runs", json=body)).status_code == 403
    assert (await viewer.get(f"/orgs/{org}/routes/{route}/runs")).status_code == 200


async def test_another_organizations_runs_are_not_found(api):
    alice, alice_org, alice_route, alice_upload = await _ready_upload(api, email="a@example.com")
    run = (
        await alice.post(
            f"/orgs/{alice_org}/routes/{alice_route}/runs", json={"upload_id": alice_upload}
        )
    ).json()
    await api.run_jobs()
    bob, bob_org, bob_route, _ = await _ready_upload(api, email="b@example.com")
    for path in (
        f"/orgs/{alice_org}/runs/{run['id']}",
        f"/orgs/{bob_org}/runs/{run['id']}",
        f"/orgs/{bob_org}/runs/{run['id']}/result",
        f"/orgs/{alice_org}/routes/{alice_route}/runs",
        f"/orgs/{bob_org}/routes/{alice_route}/runs",
    ):
        assert (await bob.get(path)).status_code == 404, path
    # Bob's route with Alice's upload: the upload is not his.
    body = {"upload_id": alice_upload}
    assert (
        await bob.post(f"/orgs/{bob_org}/routes/{bob_route}/runs", json=body)
    ).status_code == 404
