from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_instances as routes
from brainpalace_dashboard.app import create_app


def test_list_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.service,
        "list",
        lambda: [
            {
                "id": "abc",
                "name": "foo",
                "status": "running",
                "base_url": "http://127.0.0.1:8001",
                "project_root": "/p/foo",
                "pid": 1,
                "mode": "project",
                "started_at": "",
            }
        ],
    )
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "abc"


def test_start_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.service, "start", lambda id_: {"pid": 7, "base_url": "http://x"}
    )
    client = TestClient(create_app())
    resp = client.post("/dashboard/api/instances/abc/start")
    assert resp.status_code == 200
    assert resp.json()["pid"] == 7


def test_stop_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.service,
        "stop",
        lambda id_, force=False: {"id": id_, "status": "stopped"},
    )
    client = TestClient(create_app())
    resp = client.post("/dashboard/api/instances/abc/stop")
    assert resp.json()["status"] == "stopped"


def test_register_and_forget_endpoints(monkeypatch) -> None:
    monkeypatch.setattr(
        routes.service, "register", lambda path: {"id": "new", "project_root": path}
    )
    monkeypatch.setattr(
        routes.service, "forget", lambda id_: {"id": id_, "forgotten": True}
    )
    client = TestClient(create_app())
    r1 = client.post("/dashboard/api/instances/register", json={"path": "/p/bar"})
    assert r1.json()["id"] == "new"
    r2 = client.delete("/dashboard/api/instances/abc")
    assert r2.json()["forgotten"] is True
