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


def test_get_config_effective_route(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # empty global
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/config/effective")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embedding.provider"]["value"] == "openai"
    assert body["embedding.provider"]["source"] == "project"
    # Project-sourced keys carry the inherited-if-unset fallback.
    assert "inherited" in body["embedding.provider"]
    # An unset key falls back to its code default with source "default".
    assert body["reranker.enabled"]["source"] == "default"


def test_patch_config_applies_staged_unset(monkeypatch, tmp_path):
    """Save with `unset` removes the key in the same write (staged inherit)."""
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-small\n"
    )
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={
            "values": {"embedding": {"provider": "openai"}},
            "unset": ["embedding.model"],
            "restart": False,
        },
    )
    assert resp.status_code == 200
    import yaml

    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "openai"
    # The reverted key is gone → it inherits global / code default again.
    assert "model" not in saved["embedding"]


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


def test_post_config_unset_route(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # empty global
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("bm25:\n  language: hr\n")
    client = TestClient(create_app())
    resp = client.post(
        "/dashboard/api/instances/abc/config/unset",
        json={"dotpaths": ["bm25.language"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["removed"] == ["bm25.language"]
    # No global → inherits the code default ("en", source "default").
    assert body["effective"]["bm25.language"] == {"value": "en", "source": "default"}
    import yaml as _yaml

    assert (_yaml.safe_load((tmp_path / "config.yaml").read_text()) or {}) == {}


# --------------------------------------------------------------------------- #
# Task 4e — dashboard prefills extraction.provider_context_tokens             #
# --------------------------------------------------------------------------- #


def test_patch_config_prefills_context_tokens_on_model_selection(monkeypatch, tmp_path):
    """Setting summarization.model for a known provider in the dashboard should
    prefill extraction.provider_context_tokens into the written config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("")  # empty project config
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={
            "values": {
                "summarization": {
                    "provider": "anthropic",
                    "model": "claude-3-5-sonnet",
                }
            },
            "unset": [],
            "restart": False,
            "force_reindex": False,
        },
    )
    assert resp.status_code == 200, resp.text
    import yaml as _yaml

    written = _yaml.safe_load((tmp_path / "config.yaml").read_text()) or {}
    ext = written.get("extraction", {})
    assert ext.get("provider_context_tokens") == 200000  # anthropic 200k
