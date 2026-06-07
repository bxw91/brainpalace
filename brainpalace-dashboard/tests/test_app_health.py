from fastapi.testclient import TestClient

from brainpalace_dashboard.app import create_app


def test_health_route_returns_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
