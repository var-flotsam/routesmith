from fastapi.testclient import TestClient

from starboard.api.app import create_app


def test_healthz_answers_without_a_database():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_openapi_spec_is_published():
    spec = TestClient(create_app()).get("/openapi.json").json()
    assert spec["info"]["title"] == "Starboard Routing"
    assert "/healthz" in spec["paths"]


def test_a_method_a_path_does_not_take_lists_the_ones_it_does():
    client = TestClient(create_app())
    response = client.options("/orgs/00000000-0000-0000-0000-000000000000/members")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, PUT"
