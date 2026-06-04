"""Tests for the opt-in, window-safe drain loop (`drain-tick`)."""

from __future__ import annotations

import json
import os

from click.testing import CliRunner

from brainpalace_cli.commands.session_drain_loop import (
    DEFAULT_EMPTY_STOP,
    acquire_lock,
    read_heartbeat,
    read_streak,
    release_lock,
    resolve_empty_stop,
    write_heartbeat,
    write_streak,
)


def _state(tmp_path):
    s = tmp_path / ".brainpalace"
    s.mkdir(parents=True, exist_ok=True)
    return s


# --------------------------------------------------------------------------- #
# atomic lock
# --------------------------------------------------------------------------- #
def test_acquire_lock_succeeds_on_free_dir(tmp_path):
    state = _state(tmp_path)
    assert acquire_lock(state, now=1000.0, pid=4321, slack=900) is True
    assert (state / "drain-loop.lock").exists()


def test_acquire_lock_blocks_when_live_lock_held(tmp_path):
    state = _state(tmp_path)
    # A live holder: our own pid, fresh ts.
    assert acquire_lock(state, now=1000.0, pid=os.getpid(), slack=900) is True
    # A second drainer must be refused.
    assert acquire_lock(state, now=1001.0, pid=5555, slack=900) is False


def test_acquire_lock_reclaims_dead_pid(tmp_path):
    state = _state(tmp_path)
    # Write a lock owned by a pid that does not exist.
    (state / "drain-loop.lock").write_text("999999 1000.0")
    assert acquire_lock(state, now=1001.0, pid=4321, slack=900) is True


def test_acquire_lock_reclaims_expired_ts(tmp_path):
    state = _state(tmp_path)
    # Live pid but ts older than slack → stale → reclaimable.
    (state / "drain-loop.lock").write_text(f"{os.getpid()} 1000.0")
    assert acquire_lock(state, now=1000.0 + 901, pid=4321, slack=900) is True


def test_release_lock_only_removes_own(tmp_path):
    state = _state(tmp_path)
    acquire_lock(state, now=1000.0, pid=4321, slack=900)
    release_lock(state, pid=9999)  # not the owner → no-op
    assert (state / "drain-loop.lock").exists()
    release_lock(state, pid=4321)  # owner → removed
    assert not (state / "drain-loop.lock").exists()


# --------------------------------------------------------------------------- #
# heartbeat + streak + knob
# --------------------------------------------------------------------------- #
def test_heartbeat_roundtrip(tmp_path):
    state = _state(tmp_path)
    assert read_heartbeat(state) is None
    write_heartbeat(state, now=1234.5)
    assert read_heartbeat(state) == 1234.5


def test_streak_roundtrip_and_floor(tmp_path):
    state = _state(tmp_path)
    assert read_streak(state) == 0  # absent → 0
    write_streak(state, 4)
    assert read_streak(state) == 4
    write_streak(state, -2)  # floored at 0
    assert read_streak(state) == 0


def test_streak_read_tolerates_garbage(tmp_path):
    state = _state(tmp_path)
    (state / "drain-loop.state").write_text("not-an-int")
    assert read_streak(state) == 0


def test_resolve_empty_stop_default(tmp_path):
    tmp_path.joinpath(".brainpalace").mkdir()
    assert resolve_empty_stop(tmp_path) == DEFAULT_EMPTY_STOP


def test_resolve_empty_stop_env_override(tmp_path, monkeypatch):
    tmp_path.joinpath(".brainpalace").mkdir()
    monkeypatch.setenv("SESSION_DRAIN_EMPTY_STOP", "5")
    assert resolve_empty_stop(tmp_path) == 5


def test_resolve_empty_stop_floor_is_one(tmp_path, monkeypatch):
    tmp_path.joinpath(".brainpalace").mkdir()
    monkeypatch.setenv("SESSION_DRAIN_EMPTY_STOP", "0")
    assert resolve_empty_stop(tmp_path) == 1  # never auto-disable looping to 0


# --------------------------------------------------------------------------- #
# drain_tick
# --------------------------------------------------------------------------- #
from brainpalace_cli.commands.session_drain_loop import drain_tick  # noqa: E402


def _patch_pending(monkeypatch, pairs):
    """Make ``drain_queue`` (called inside ``drain_tick``) source from the gap."""
    from brainpalace_cli.commands import session_drain as sd

    monkeypatch.setattr(sd, "pending_ids", lambda root, now=None: list(pairs))


def _unresolved(tmp_path, *ids):
    """``(sid, archive_path)`` pairs whose files don't exist → inf size."""
    return [(sid, str(tmp_path / "gone" / f"{sid}.jsonl")) for sid in ids]


def test_drain_tick_skips_non_subagent_mode(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _unresolved(tmp_path, "a", "b"))
    res = drain_tick(tmp_path, mode="provider", now=1000.0, pid=4321)
    assert res["status"] == "skipped"  # bails before draining the gap
    assert res["should_stop"] is True
    assert res["drained"] == []


def test_drain_tick_drains_one_batch_and_resets_streak(tmp_path, monkeypatch):
    # Unresolved transcripts → inf size → first id drains alone (deterministic).
    _patch_pending(monkeypatch, _unresolved(tmp_path, "a", "b"))
    write_streak(_state(tmp_path), 2)
    res = drain_tick(tmp_path, mode="subagent", now=1000.0, pid=4321)
    assert res["status"] == "ok"
    assert res["drained"] == ["a"]
    assert res["remaining"] == 1
    assert res["empty_streak"] == 0  # a non-empty drain resets the streak
    assert res["should_stop"] is False
    # Lock released after the tick.
    assert not (tmp_path / ".brainpalace" / "drain-loop.lock").exists()
    # Heartbeat written.
    assert read_heartbeat(tmp_path / ".brainpalace") == 1000.0


def test_drain_tick_empty_increments_streak_then_stops(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, [])  # no pending sessions
    r1 = drain_tick(tmp_path, mode="subagent", empty_stop=2, now=1000.0, pid=1)
    assert r1["drained"] == [] and r1["empty_streak"] == 1
    assert r1["should_stop"] is False
    r2 = drain_tick(tmp_path, mode="subagent", empty_stop=2, now=1001.0, pid=1)
    assert r2["empty_streak"] == 2 and r2["should_stop"] is True


def test_drain_tick_returns_locked_when_drainer_live(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _unresolved(tmp_path, "a"))
    state = _state(tmp_path)
    # Pre-hold a live lock (current process).
    acquire_lock(state, now=1000.0, pid=os.getpid(), slack=900)
    res = drain_tick(tmp_path, mode="subagent", now=1001.0, pid=4321)
    assert res["status"] == "locked"  # never drained — another drainer holds the lock
    assert res["should_stop"] is True


def test_drain_tick_auto_mode_without_plugin_is_provider_skip(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _unresolved(tmp_path, "a"))
    res = drain_tick(
        tmp_path, mode="auto", plugin_installed=False, now=1000.0, pid=4321
    )
    assert res["status"] == "skipped"  # auto + no plugin → provider → not subagent


# --------------------------------------------------------------------------- #
# drain-tick CLI command
# --------------------------------------------------------------------------- #
from brainpalace_cli.commands.session_drain_loop import drain_tick_command  # noqa: E402


def test_cli_drain_tick_json_skipped(tmp_path):
    # No config → read_extract_mode defaults to subagent; no archive → empty gap.
    runner = CliRunner()
    result = runner.invoke(
        drain_tick_command,
        ["--project", str(tmp_path), "--json"],
        env={"SESSION_DRAIN_EMPTY_STOP": "2"},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert set(payload) == {
        "status",
        "drained",
        "remaining",
        "empty_streak",
        "should_stop",
    }


def test_cli_drain_tick_no_project(tmp_path):
    runner = CliRunner()
    # No --project and a cwd with no .brainpalace/ anywhere up the tree → discovery
    # returns None → the `no-project` branch (passing --project always resolves a
    # path, so it would never exercise this).
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(drain_tick_command, ["--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "no-project"
