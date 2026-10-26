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
    # Four stops beside streets, one in the middle of a block, then a bad row.
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
    # s5 sits mid-block, as near one street as another: the planner picks.
    assert [(s["stop_id"], s["review_reason"]) for s in review] == [("s5", "ambiguous_street")]
    assert len(review[0]["candidate_segment_ids"]) >= 2
    # Each candidate comes drawn, with the curb the stop's point is on.
    streets = review[0]["candidate_streets"]
    assert [c["segment_id"] for c in streets] == review[0]["candidate_segment_ids"]
    assert all(len(c["line"]) >= 2 and c["curb_side"] in ("left", "right") for c in streets)
    assert review[0]["lon"] is not None and review[0]["lat"] is not None
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


async def _in_review(api):
    client, org, route = await _setup(api)
    upload = (await _upload(client, org, route)).json()
    await api.run_jobs()
    base = f"/orgs/{org}/uploads/{upload['id']}"
    (item,) = (await client.get(f"{base}/stops?state=review")).json()
    return client, org, base, item


async def test_a_planner_clears_a_review_item_by_picking_a_candidate_street(api):
    client, _, base, item = await _in_review(api)
    street = item["candidate_segment_ids"][0]
    placed = await client.put(
        f"{base}/stops/{item['stop_id']}/placement",
        json={"segment_id": street, "curb_side": "left"},
    )
    assert placed.status_code == 200
    assert (placed.json()["state"], placed.json()["segment_id"]) == ("snapped", street)
    upload = (await client.get(base)).json()
    assert (upload["stops_snapped"], upload["stops_in_review"]) == (5, 0)


async def test_a_street_that_is_not_a_candidate_is_refused(api):
    client, _, base, item = await _in_review(api)
    response = await client.put(
        f"{base}/stops/{item['stop_id']}/placement",
        json={"segment_id": "somewhere-else", "curb_side": "right"},
    )
    assert response.status_code == 409


async def test_a_stop_that_snapped_on_its_own_is_not_placed_again(api):
    client, _, base, _ = await _in_review(api)
    response = await client.put(
        f"{base}/stops/s1/placement", json={"segment_id": "h-0-0", "curb_side": "right"}
    )
    assert response.status_code == 409


async def test_a_planner_excludes_a_stop(api):
    client, _, base, item = await _in_review(api)
    response = await client.put(f"{base}/stops/{item['stop_id']}/exclusion")
    assert response.status_code == 200
    upload = (await client.get(base)).json()
    assert (upload["stops_in_review"], upload["stops_excluded"]) == (0, 1)


async def test_another_organizations_stops_cannot_be_placed_or_excluded(api):
    _, _, base, item = await _in_review(api)
    bob = await api.signed_in("bob@example.com")
    bob_org = (await bob.post("/orgs", json={"name": "Bob Hauling"})).json()["id"]
    upload_id = base.rsplit("/", 1)[1]
    for prefix in (base, f"/orgs/{bob_org}/uploads/{upload_id}"):
        stop = f"{prefix}/stops/{item['stop_id']}"
        body = {"segment_id": item["candidate_segment_ids"][0], "curb_side": "left"}
        assert (await bob.put(f"{stop}/placement", json=body)).status_code == 404
        assert (await bob.put(f"{stop}/exclusion")).status_code == 404


async def test_stops_given_by_address_are_geocoded_and_doubtful_ones_reviewed(api):
    client, org, route = await _setup(api)
    body = (
        b"stop_id,current_sequence,address,city,state\n"
        b"a,1,20 -10,Town,CT\n"  # found as written
        b"b,2,maybe 60 -10,Town,CT\n"  # found after the geocoder changed the address
        b"c,3,twice,Town,CT\n"  # more than one place fits
        b"d,4,nowhere,Town,CT\n"  # not found
    )
    upload = (await _upload(client, org, route, body)).json()
    assert await api.run_jobs() == ["ready"]
    base = f"/orgs/{org}/uploads/{upload['id']}"
    stops = {s["stop_id"]: s for s in (await client.get(f"{base}/stops")).json()}
    assert stops["a"]["state"] == "snapped"
    assert (stops["b"]["review_reason"], len(stops["b"]["candidate_segment_ids"])) == (
        "address_inexact",
        1,
    )
    assert stops["c"]["review_reason"] == "address_ambiguous"
    assert stops["d"]["review_reason"] == "address_not_found"
    # The planner confirms the inexact one and leaves the unplaced ones out.
    b = stops["b"]
    confirmed = await client.put(
        f"{base}/stops/b/placement",
        json={"segment_id": b["candidate_segment_ids"][0], "curb_side": "right"},
    )
    assert confirmed.status_code == 200
    for stop_id in ("c", "d"):
        assert (await client.put(f"{base}/stops/{stop_id}/exclusion")).status_code == 200
    done = (await client.get(base)).json()
    assert (done["stops_snapped"], done["stops_in_review"], done["stops_excluded"]) == (2, 0, 2)
