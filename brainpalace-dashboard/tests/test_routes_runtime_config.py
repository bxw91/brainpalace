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


def test_runtime_config_effective_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"bind_host": "0.0.0.0"}))
    client = TestClient(create_app())
    body = client.get("/dashboard/api/instances/abc/runtime-config/effective").json()
    # File-set field: source "file" + the code default it would revert to.
    assert body["bind_host"]["value"] == "0.0.0.0"
    assert body["bind_host"]["source"] == "file"
    assert body["bind_host"]["inherited"] == {"value": "127.0.0.1", "source": "default"}
    # Unset field: the code default, source "default", nothing to inherit.
    assert body["port_range_start"]["source"] == "default"
    assert body["port_range_start"]["value"] == 8000
    assert body["port_range_start"]["inherited"] is None


def test_patch_runtime_config_unset_reverts_to_default(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"bind_host": "0.0.0.0", "chunk_size": 512})
    )
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/runtime-config",
        json={"values": {}, "unset": ["bind_host"], "restart": False},
    )
    assert resp.status_code == 200
    saved = json.loads((tmp_path / "config.json").read_text())
    # The unset bind key is gone (reverts to the code default on read); the
    # non-bind key is preserved.
    assert "bind_host" not in saved
    assert saved["chunk_size"] == 512


def test_runtime_effective_resolves_project_over_global_over_default(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "cfg" / "brainpalace").mkdir(parents=True)
    # Global sets the host; project pins a port; auto_port falls to code default.
    (tmp_path / "cfg" / "brainpalace" / "config.json").write_text(
        json.dumps({"bind_host": "0.0.0.0"})
    )
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"port_range_start": 9000}))
    client = TestClient(create_app())
    body = client.get("/dashboard/api/instances/abc/runtime-config/effective").json()
    assert body["bind_host"] == {
        "value": "0.0.0.0",
        "source": "global",
        "inherited": None,
    }
    # Project-set key inherits the GLOBAL value when reverted (here global unset
    # for this key → code default).
    assert body["port_range_start"]["value"] == 9000
    assert body["port_range_start"]["source"] == "file"
    assert body["port_range_start"]["inherited"] == {"value": 8000, "source": "default"}
    assert body["auto_port"]["source"] == "default"


def test_global_runtime_effective_and_patch(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    client = TestClient(create_app())
    # Empty global → all code defaults.
    body = client.get("/dashboard/api/global-runtime-config/effective").json()
    assert body["bind_host"] == {
        "value": "127.0.0.1",
        "source": "default",
        "inherited": None,
    }
    # Write a machine-wide default.
    resp = client.patch(
        "/dashboard/api/global-runtime-config",
        json={"values": {"bind_host": "0.0.0.0"}, "restart": False},
    )
    assert resp.status_code == 200
    saved = json.loads((tmp_path / "cfg" / "brainpalace" / "config.json").read_text())
    assert saved["bind_host"] == "0.0.0.0"
    # Now effective reports it as global with the code-default fallback.
    body = client.get("/dashboard/api/global-runtime-config/effective").json()
    assert body["bind_host"]["source"] == "global"
    assert body["bind_host"]["inherited"] == {"value": "127.0.0.1", "source": "default"}


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
