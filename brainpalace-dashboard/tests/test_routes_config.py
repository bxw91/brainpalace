from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_config as rc
from brainpalace_dashboard.app import create_app


def test_schema_route():
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/schema")
    assert resp.status_code == 200
    assert any(s["key"] == "embedding" for s in resp.json()["sections"])


def test_get_config_route(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/config")
    assert resp.json()["embedding"]["provider"] == "openai"


def test_patch_config_validation_error(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={"values": {"embedding": {"provider": "bogus"}}, "restart": False},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]


def test_patch_config_ok_with_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    restarted = {}
    monkeypatch.setattr(
        rc.instance_service,
        "restart",
        lambda id_: restarted.setdefault("x", True),
    )
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={"values": {"embedding": {"provider": "ollama"}}, "restart": True},
    )
    assert resp.status_code == 200
    assert resp.json()["restarted"] is True
    assert restarted == {"x": True}
