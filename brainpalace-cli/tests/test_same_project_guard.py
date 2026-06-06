"""Defense-in-depth: never spawn a second server for the same project.

Even when runtime.json is missing or stale (so the start_command up-front guard
can't fire), launch_server must detect an already-running server for THIS
project_root by probing /health across the port range, and refuse to spawn a
duplicate. A server for a *different* project on a port must not block us.
"""

from __future__ import annotations

import json

import pytest

import brainpalace_cli.commands.start as start_mod


def test_find_same_project_server_matches_project_root():
    """Returns the base_url of a probed port whose /health reports our root."""

    def fake_probe(base_url):
        if base_url.endswith(":8002"):
            return {"status": "healthy", "project_root": "/proj/A"}
        if base_url.endswith(":8000"):
            return {"status": "healthy", "project_root": "/proj/OTHER"}
        return None

    found = start_mod.find_same_project_server(
        "127.0.0.1", "/proj/A", 8000, 8003, probe=fake_probe
    )
    assert found == "http://127.0.0.1:8002"


def test_find_same_project_server_ignores_foreign_projects():
    """A different project's server on a port must not be treated as ours."""

    def fake_probe(base_url):
        return {"status": "healthy", "project_root": "/proj/OTHER"}

    found = start_mod.find_same_project_server(
        "127.0.0.1", "/proj/A", 8000, 8002, probe=fake_probe
    )
    assert found is None


def test_launch_server_refuses_duplicate_same_project(tmp_path, monkeypatch):
    """launch_server raises ServerAlreadyRunningError and never spawns when a
    same-project server already exists."""
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "auto_port": True})
    )

    monkeypatch.setattr(
        start_mod,
        "find_same_project_server",
        lambda *a, **k: "http://127.0.0.1:8000",
    )

    def boom_popen(*a, **k):
        raise AssertionError("must not spawn a duplicate server")

    monkeypatch.setattr(start_mod.subprocess, "Popen", boom_popen)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    with pytest.raises(start_mod.ServerAlreadyRunningError) as exc:
        start_mod.launch_server(project_root=tmp_path, state_dir=state_dir, timeout=5)
    assert exc.value.base_url == "http://127.0.0.1:8000"


def test_launch_server_spawns_when_no_duplicate(tmp_path, monkeypatch):
    """No same-project server => normal spawn proceeds."""
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "port": 8131, "auto_port": False})
    )

    class FakeProc:
        pid = 555

        def poll(self):
            return None

    monkeypatch.setattr(start_mod, "find_same_project_server", lambda *a, **k: None)
    monkeypatch.setattr(start_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    runtime = start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, timeout=5
    )
    assert runtime["pid"] == 555
