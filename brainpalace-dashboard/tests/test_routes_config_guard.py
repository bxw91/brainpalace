import pytest
from fastapi.testclient import TestClient

from brainpalace_dashboard.api import routes_config as rc
from brainpalace_dashboard.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    sd = tmp_path / ".brainpalace"
    sd.mkdir()
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
    )
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: sd)
    return TestClient(create_app())


_BREAKING = {
    "values": {"embedding": {"provider": "openai", "model": "text-embedding-3-small"}}
}


def test_blocks_breaking_change_when_data_present(client, monkeypatch):
    async def fp(id_):
        return {"has_data": True, "doc_count": 10, "chunk_count": 99}

    monkeypatch.setattr(rc.proxy_service, "fetch_fingerprint", fp)
    resp = client.patch("/dashboard/api/instances/x/config", json=_BREAKING)
    assert resp.status_code == 409
    body = resp.json()
    assert body["conflict"] == "data_incompatible"
    assert body["counts"] == {"documents": 10, "chunks": 99}


def test_allows_when_no_data(client, monkeypatch):
    async def fp(id_):
        return {"has_data": False}

    monkeypatch.setattr(rc.proxy_service, "fetch_fingerprint", fp)
    resp = client.patch("/dashboard/api/instances/x/config", json=_BREAKING)
    assert resp.status_code == 200


def test_allows_when_server_unreachable(client, monkeypatch):
    async def fp(id_):
        return None

    monkeypatch.setattr(rc.proxy_service, "fetch_fingerprint", fp)
    resp = client.patch("/dashboard/api/instances/x/config", json=_BREAKING)
    assert resp.status_code == 200


def test_noop_materializing_inherited_default_not_blocked(monkeypatch, tmp_path):
    """The reported bug: project leaves embedding unset (inherits the default),
    the save writes that SAME effective default (null -> openai /
    text-embedding-3-large). Effective embedding is unchanged, so it must NOT be
    blocked even with indexed data present."""
    # Isolate from any real global config so effective() falls back to defaults.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    sd = tmp_path / ".brainpalace"
    sd.mkdir()
    (sd / "config.yaml").write_text("graphrag:\n  enabled: true\n")  # no embedding
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: sd)
    client = TestClient(create_app())

    async def fp(id_):
        return {"has_data": True, "doc_count": 10, "chunk_count": 99}

    monkeypatch.setattr(rc.proxy_service, "fetch_fingerprint", fp)
    resp = client.patch(
        "/dashboard/api/instances/x/config",
        json={
            "values": {
                "embedding": {
                    "provider": "openai",
                    "model": "text-embedding-3-large",
                }
            }
        },
    )
    assert resp.status_code == 200, resp.json()


def test_force_reindex_skips_guard_and_triggers(client, monkeypatch):
    triggered = {}

    async def fp(id_):
        return {"has_data": True, "doc_count": 10, "chunk_count": 99}

    async def reindex(id_):
        triggered["id"] = id_
        return 2

    monkeypatch.setattr(rc.proxy_service, "fetch_fingerprint", fp)
    monkeypatch.setattr(rc.proxy_service, "trigger_full_reindex", reindex)
    resp = client.patch(
        "/dashboard/api/instances/x/config",
        json={**_BREAKING, "force_reindex": True},
    )
    assert resp.status_code == 200
    assert resp.json().get("reindex_triggered") == 2
    assert triggered["id"] == "x"
