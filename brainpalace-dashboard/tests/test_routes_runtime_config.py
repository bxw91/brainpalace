"""Per-instance runtime-config endpoints — the config.json bind editor.

``GET/PATCH /dashboard/api/instances/{id}/runtime-config`` read/write the four
bind fields (bind_host / port_range_start / port_range_end / auto_port). Writes
validate (port 1–65535, start<=end, host non-empty) and need a server restart to
apply (``restart_required`` in the response).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_config as rc
from brainpalace_dashboard.app import create_app


def test_get_runtime_config_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/runtime-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "bind_host": "127.0.0.1",
        "port_range_start": 8000,
        "port_range_end": 8100,
        "auto_port": True,
    }


def test_get_runtime_config_reads_file(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"bind_host": "0.0.0.0", "port_range_start": 9000})
    )
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/runtime-config")
    assert resp.json()["bind_host"] == "0.0.0.0"
    assert resp.json()["port_range_start"] == 9000


def test_patch_runtime_config_writes_and_preserves_other_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "chunk_size": 512})
    )
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={
            "values": {"bind_host": "0.0.0.0", "port_range_end": 9100},
            "restart": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["restart_required"] is True
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["bind_host"] == "0.0.0.0"
    assert saved["port_range_end"] == 9100
    # Non-bind keys are preserved verbatim.
    assert saved["chunk_size"] == 512


def test_patch_runtime_config_rejects_bad_port(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={"values": {"port_range_start": 70000}, "restart": False},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "port_range_start"


def test_patch_runtime_config_rejects_inverted_range(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={
            "values": {"port_range_start": 9000, "port_range_end": 8000},
            "restart": False,
        },
    )
    assert resp.status_code == 422
    fields = {e["field"] for e in resp.json()["errors"]}
    assert "port_range_end" in fields


def test_patch_runtime_config_rejects_empty_host(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={"values": {"bind_host": "  "}, "restart": False},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "bind_host"


def test_patch_runtime_config_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    restarted = {}
    monkeypatch.setattr(
        rc.instance_service, "restart", lambda id_: restarted.setdefault("x", True)
    )
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={"values": {"bind_host": "0.0.0.0"}, "restart": True},
    )
    assert resp.status_code == 200
    assert resp.json()["restarted"] is True
    assert resp.json()["restart_required"] is False
    assert restarted == {"x": True}
