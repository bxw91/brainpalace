"""Tests for the existing-server guard in start_command.

Regression cover for the duplicate-server incident: a live-but-busy server
(health check times out) must NOT be treated as stale, wiped, and replaced by a
second server writing the same data dir. And the CLI must never unlink the
``brainpalace.lock`` file the running server holds an flock on — doing so
defeats the OS single-instance guarantee (flock binds to the inode).
"""

from __future__ import annotations

import brainpalace_cli.commands.start as start_mod


def test_classify_running_when_alive_and_healthy():
    """Alive pid + passing health check => report the running server."""
    runtime = {"pid": 100, "base_url": "http://127.0.0.1:8000"}
    action = start_mod.classify_existing_server(
        runtime,
        alive_fn=lambda pid: True,
        health_fn=lambda url: True,
    )
    assert action == "running"


def test_classify_unresponsive_when_alive_but_unhealthy():
    """Alive pid + failing health check => unresponsive, NOT stale.

    This is the incident trigger: a busy server that can't answer /health in
    time must never be reclassified as dead.
    """
    runtime = {"pid": 100, "base_url": "http://127.0.0.1:8000"}
    action = start_mod.classify_existing_server(
        runtime,
        alive_fn=lambda pid: True,
        health_fn=lambda url: False,
    )
    assert action == "unresponsive"


def test_classify_stale_when_pid_dead():
    """Dead pid => stale (safe to clean up and start fresh)."""
    runtime = {"pid": 100, "base_url": "http://127.0.0.1:8000"}
    action = start_mod.classify_existing_server(
        runtime,
        alive_fn=lambda pid: False,
        health_fn=lambda url: False,
    )
    assert action == "stale"


def test_classify_stale_when_no_runtime():
    """Missing runtime => stale."""
    action = start_mod.classify_existing_server(
        None,
        alive_fn=lambda pid: True,
        health_fn=lambda url: True,
    )
    assert action == "stale"


def test_cleanup_stale_never_unlinks_lock_file(tmp_path):
    """cleanup_stale must leave brainpalace.lock alone.

    The running server holds an flock on this file's inode; unlinking it lets a
    second server create a fresh inode and acquire the lock, defeating the
    single-instance guarantee. cleanup_stale may remove pid/runtime only.
    """
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    lock = state_dir / start_mod.LOCK_FILE
    pid = state_dir / start_mod.PID_FILE
    runtime = state_dir / start_mod.RUNTIME_FILE
    for f in (lock, pid, runtime):
        f.write_text("x")

    start_mod.cleanup_stale(state_dir)

    assert lock.exists(), "cleanup_stale must not delete the lock file"
    assert not pid.exists()
    assert not runtime.exists()
