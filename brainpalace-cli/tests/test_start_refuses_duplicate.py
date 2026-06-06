"""start_command must never spawn a second server over a live one.

Incident regression: when a server is alive but its /health check fails (busy
indexing), the old code wiped runtime/lock and spawned a duplicate on the next
free port. The fix: refuse with a non-zero exit and leave state untouched.
"""

from __future__ import annotations

import json
import os

from click.testing import CliRunner

import brainpalace_cli.commands.start as start_mod


def _make_project(tmp_path, *, pid: int):
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "auto_port": True})
    )
    (state_dir / start_mod.RUNTIME_FILE).write_text(
        json.dumps(
            {
                "pid": pid,
                "base_url": "http://127.0.0.1:8000",
                "project_root": str(tmp_path),
            }
        )
    )
    (state_dir / start_mod.LOCK_FILE).write_text("")
    return state_dir


def test_start_refuses_when_live_server_unresponsive(tmp_path, monkeypatch):
    """Live pid + failing health => exit non-zero, no launch, lock preserved."""
    state_dir = _make_project(tmp_path, pid=os.getpid())  # this process: alive

    launched: dict[str, bool] = {"called": False}

    def fake_launch(*args, **kwargs):
        launched["called"] = True
        raise AssertionError("launch_server must not be called for a live server")

    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: False)
    monkeypatch.setattr(start_mod, "launch_server", fake_launch)
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)
    monkeypatch.setattr(start_mod, "EXISTING_SERVER_HEALTH_RETRY_DELAY", 0.0)

    result = CliRunner().invoke(start_mod.start_command, ["--path", str(tmp_path)])

    assert launched["called"] is False
    assert result.exit_code != 0
    # The lock the running server holds must survive.
    assert (state_dir / start_mod.LOCK_FILE).exists()
    # runtime.json must NOT be wiped for a live server.
    assert (state_dir / start_mod.RUNTIME_FILE).exists()


def test_start_reports_running_when_healthy(tmp_path, monkeypatch):
    """Live pid + passing health => report already running, no launch."""
    _make_project(tmp_path, pid=os.getpid())

    def fake_launch(*args, **kwargs):
        raise AssertionError("launch_server must not be called when already healthy")

    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "launch_server", fake_launch)
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)

    result = CliRunner().invoke(start_mod.start_command, ["--path", str(tmp_path)])

    assert result.exit_code == 0
