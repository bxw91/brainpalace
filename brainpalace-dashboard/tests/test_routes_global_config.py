"""Global-config endpoints — the machine-wide XDG config.yaml editor.

``GET/PATCH /dashboard/api/global-config`` mirror the per-project config routes
(masked read, 422 ``{errors:[...]}`` on invalid, secret-merge + atomic write),
but point at the GLOBAL file (no provenance/effective layer — it IS the global
layer).
"""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from brainpalace_dashboard.app import create_app
from brainpalace_dashboard.services.config_svc import MASK


def _xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path / "cfg" / "brainpalace" / "config.yaml"


def test_get_global_config_masks_secret(monkeypatch, tmp_path):
    path = _xdg(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("embedding:\n  provider: openai\n  api_key: sk-REAL\n")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/global-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embedding"]["provider"] == "openai"
    assert body["embedding"]["api_key"] == MASK


def test_get_global_config_empty_when_absent(monkeypatch, tmp_path):
    _xdg(monkeypatch, tmp_path)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/global-config")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_patch_global_config_writes_file(monkeypatch, tmp_path):
    path = _xdg(monkeypatch, tmp_path)
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/global-config",
        json={"values": {"embedding": {"provider": "ollama"}}, "restart": False},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    saved = yaml.safe_load(path.read_text())
    assert saved["embedding"]["provider"] == "ollama"


def test_patch_global_config_validation_error(monkeypatch, tmp_path):
    _xdg(monkeypatch, tmp_path)
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/global-config",
        json={"values": {"embedding": {"provider": "bogus"}}, "restart": False},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]


def test_patch_global_config_preserves_secret_on_mask(monkeypatch, tmp_path):
    path = _xdg(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("embedding:\n  provider: openai\n  api_key: sk-REAL\n")
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/global-config",
        json={
            "values": {"embedding": {"provider": "openai", "api_key": MASK}},
            "restart": False,
        },
    )
    assert resp.status_code == 200
    saved = yaml.safe_load(path.read_text())
    assert saved["embedding"]["api_key"] == "sk-REAL"


def test_get_global_config_effective(monkeypatch, tmp_path):
    path = _xdg(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("graphrag:\n  enabled: false\n")
    client = TestClient(create_app())
    r = client.get("/dashboard/api/global-config/effective")
    assert r.status_code == 200
    body = r.json()
    assert body["graphrag.enabled"]["source"] == "global"
    assert body["graphrag.enabled"]["value"] is False


def test_post_global_config_unset(monkeypatch, tmp_path):
    path = _xdg(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("graphrag:\n  enabled: false\n")
    client = TestClient(create_app())
    r = client.post(
        "/dashboard/api/global-config/unset",
        json={"dotpaths": ["graphrag.enabled"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] == ["graphrag.enabled"]
    assert body["effective"]["graphrag.enabled"]["source"] == "default"
