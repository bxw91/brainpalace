"""Tests for the non-Click ``launch_server`` callable extracted from start_command."""

from __future__ import annotations

import brainpalace_cli.commands.start as start_mod

# Default bind stub used across all tests: a 127.0.0.1:8000 range with
# auto_port=True so find_available_port is called (not the fixed-port path).
# Tests that need a deterministic port override ``read_bind`` themselves.
_DEFAULT_BIND = {
    "bind_host": "127.0.0.1",
    "port_range_start": 8000,
    "port_range_end": 8100,
    "auto_port": True,
}


def _stub_read_bind(bind: dict):
    """Return a monkeypatch-compatible stub for read_bind."""
    return lambda sd: bind


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
    monkeypatch.setattr(start_mod, "probe", lambda url, root, timeout=2.0: "mine")
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    # Stub read_bind: avoids the BindConfig → providers → MCP import chain that
    # fails on Python 3.12 when subprocess.Popen is replaced by a plain callable
    # (class-body annotation ``subprocess.Popen[bytes]`` is not subscriptable).
    # Also pin an explicit port so base_url is deterministic.
    monkeypatch.setattr(
        start_mod,
        "read_bind",
        _stub_read_bind(
            {
                "bind_host": "127.0.0.1",
                "port_range_start": 8123,
                "port_range_end": 8123,
                "auto_port": False,
            }
        ),
    )

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

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
    monkeypatch.setattr(start_mod, "probe", lambda url, root, timeout=2.0: "mine")
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    monkeypatch.setattr(start_mod, "read_bind", _stub_read_bind(_DEFAULT_BIND))

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

    start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, timeout=5, strict=True
    )
    assert calls["env"]["BRAINPALACE_STRICT_MODE"] == "true"


def test_launch_server_sets_no_dashboard_env(tmp_path, monkeypatch):
    """no_dashboard=True propagates BRAINPALACE_NO_DASHBOARD so the spawned
    server's self-heal won't re-spawn a dashboard behind --no-dashboard."""
    calls: dict[str, object] = {}

    class FakeProc:
        pid = 100

        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        start_mod.subprocess,
        "Popen",
        lambda cmd, **kw: calls.update(env=kw.get("env")) or FakeProc(),
    )
    monkeypatch.setattr(start_mod, "probe", lambda url, root, timeout=2.0: "mine")
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    monkeypatch.setattr(start_mod, "read_bind", _stub_read_bind(_DEFAULT_BIND))

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

    start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, timeout=5, no_dashboard=True
    )
    assert calls["env"]["BRAINPALACE_NO_DASHBOARD"] == "true"

    # Default (no_dashboard omitted) must NOT set the var.
    calls.clear()
    start_mod.launch_server(project_root=tmp_path, state_dir=state_dir, timeout=5)
    assert "BRAINPALACE_NO_DASHBOARD" not in calls["env"]


def test_launch_server_raises_on_unhealthy(tmp_path, monkeypatch):
    """A server that never becomes healthy raises RuntimeError within timeout."""

    class FakeProc:
        pid = 7

        def poll(self) -> int:
            return 1  # process already exited

    monkeypatch.setattr(start_mod.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    monkeypatch.setattr(start_mod, "probe", lambda url, root, timeout=2.0: "down")
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    monkeypatch.setattr(start_mod, "read_bind", _stub_read_bind(_DEFAULT_BIND))

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

    import pytest

    with pytest.raises(RuntimeError):
        start_mod.launch_server(project_root=tmp_path, state_dir=state_dir, timeout=1)
