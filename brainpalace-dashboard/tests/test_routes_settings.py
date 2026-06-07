"""Control-plane settings API (the dashboard's own server config)."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from brainpalace_dashboard.app import create_app


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return TestClient(create_app())


def test_get_settings_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/dashboard/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 8787
    assert body["poll_s"] == 5
    assert body["token_set"] is False
    assert body["token"] == ""  # no real token ever leaks
    assert body["autostart"] is True  # default on


def test_patch_autostart_persists(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/dashboard/api/settings", json={"autostart": False})
    assert r.status_code == 200
    # autostart is not restart-sensitive (applies on the next `brainpalace start`)
    assert "autostart" not in r.json()["restart_required"]
    assert c.get("/dashboard/api/settings").json()["autostart"] is False


def test_patch_writes_dashboard_block_and_preserves_others(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg" / "brainpalace"
    cfg_dir.mkdir(parents=True)
    # A pre-existing unrelated section must survive the write.
    (cfg_dir / "config.yaml").write_text("embedding:\n  provider: openai\n")
    c = _client(tmp_path, monkeypatch)

    r = c.patch(
        "/dashboard/api/settings",
        json={"port": 9001, "poll_s": 10, "token": "s3cret"},
    )
    assert r.status_code == 200
    assert set(r.json()["restart_required"]) == {"port", "token"}  # not poll_s

    saved = yaml.safe_load((cfg_dir / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "openai"  # preserved
    assert saved["dashboard"]["port"] == 9001
    assert saved["dashboard"]["poll_s"] == 10
    assert saved["dashboard"]["token"] == "s3cret"

    # GET now reports token_set but never the value.
    body = c.get("/dashboard/api/settings").json()
    assert body["token_set"] is True
    assert body["token"] == "********"


def test_patch_mask_keeps_existing_token(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg" / "brainpalace"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("dashboard:\n  token: keepme\n")
    c = _client(tmp_path, monkeypatch)

    # A token is configured, so the control-plane API now requires it.
    auth = {"Authorization": "Bearer keepme"}
    r = c.patch(
        "/dashboard/api/settings",
        json={"poll_s": 7, "token": "********"},
        headers=auth,
    )
    assert r.status_code == 200
    saved = yaml.safe_load((cfg_dir / "config.yaml").read_text())
    assert saved["dashboard"]["token"] == "keepme"  # mask did not overwrite


def test_patch_rejects_bad_port(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/dashboard/api/settings", json={"port": 70000})
    assert r.status_code == 422
    assert any(e["field"] == "port" for e in r.json()["errors"])


def test_update_check_reports_newer(tmp_path, monkeypatch):
    from brainpalace_dashboard.services import update_check

    # Force a fresh check and stub out PyPI + the installed version.
    update_check._cache = None
    monkeypatch.setattr(update_check, "_installed_version", lambda: "26.6.27")

    async def _fake_latest() -> str:
        return "26.7.0"

    monkeypatch.setattr(update_check, "_fetch_latest", _fake_latest)

    c = _client(tmp_path, monkeypatch)
    body = c.get("/dashboard/api/settings/update-check?force=true").json()
    assert body["current"] == "26.6.27"
    assert body["latest"] == "26.7.0"
    assert body["update_available"] is True


def test_update_check_silent_on_fetch_failure(tmp_path, monkeypatch):
    from brainpalace_dashboard.services import update_check

    update_check._cache = None
    monkeypatch.setattr(update_check, "_installed_version", lambda: "26.6.27")

    async def _fail() -> None:
        return None  # network/parse failure path

    monkeypatch.setattr(update_check, "_fetch_latest", _fail)

    c = _client(tmp_path, monkeypatch)
    r = c.get("/dashboard/api/settings/update-check?force=true")
    assert r.status_code == 200
    body = r.json()
    assert body["latest"] is None
    assert body["update_available"] is False
