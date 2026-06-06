"""Tests for the non-Click ``launch_server`` callable extracted from start_command."""

from __future__ import annotations

import json

import brainpalace_cli.commands.start as start_mod


def test_launch_server_is_callable_and_returns_runtime(tmp_path, monkeypatch):
    """launch_server spawns uvicorn and returns a runtime dict without Click."""
    calls: dict[str, object] = {}

    class FakeProc:
        pid = 4321

        def poll(self) -> None:
            return None

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["env"] = kwargs.get("env")
        return FakeProc()

    monkeypatch.setattr(start_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    # Real CLI config lives in config.json; pin an explicit port with auto_port off
    # so the resolved base_url is deterministic.
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "port": 8123, "auto_port": False})
    )

    runtime = start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, host=None, port=None, timeout=5
    )

    assert runtime["pid"] == 4321
    assert runtime["base_url"] == "http://127.0.0.1:8123"
    # cmd is a list: [sys.executable, "-m", "uvicorn", "brainpalace_server...", ...]
    assert "uvicorn" in calls["cmd"]
    env = calls["env"]
    assert env["BRAINPALACE_STATE_DIR"] == str(state_dir)
    assert env["BRAINPALACE_PROJECT_ROOT"] == str(tmp_path)


def test_launch_server_sets_strict_env(tmp_path, monkeypatch):
    """strict=True propagates BRAINPALACE_STRICT_MODE to the spawned server."""
    calls: dict[str, object] = {}

    class FakeProc:
        pid = 99

        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        start_mod.subprocess,
        "Popen",
        lambda cmd, **kw: calls.update(env=kw.get("env")) or FakeProc(),
    )
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "port": 8124, "auto_port": False})
    )

    start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, timeout=5, strict=True
    )
    assert calls["env"]["BRAINPALACE_STRICT_MODE"] == "true"


def test_launch_server_raises_on_unhealthy(tmp_path, monkeypatch):
    """A server that never becomes healthy raises RuntimeError within timeout."""

    class FakeProc:
        pid = 7

        def poll(self) -> int:
            return 1  # process already exited

    monkeypatch.setattr(start_mod.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: False)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "port": 8125, "auto_port": False})
    )

    import pytest

    with pytest.raises(RuntimeError):
        start_mod.launch_server(project_root=tmp_path, state_dir=state_dir, timeout=1)
