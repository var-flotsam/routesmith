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
