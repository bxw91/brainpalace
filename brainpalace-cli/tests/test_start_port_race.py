"""Regression tests for the concurrent-start port race.

Two ``bp start`` invocations for DIFFERENT projects, launched a few seconds
apart, both auto-picked port 8000 and only the second survived. Two defects
compounded:

1. ``find_available_port`` binds a probe socket, CLOSES it, then returns the
   number — a TOCTOU window in which a second start picks the same port before
   the first server actually binds it.
2. The post-spawn wait used ``check_health`` (reachability: *any* 200), not
   ``probe`` (identity). So a start whose own child lost the bind race and died
   still saw the 200 from the OTHER project's server on that port and reported
   success — adopting a foreign server with a dead PID.

The fix: identity-check the wait (accept only ``"mine"``) and, on a lost race,
retry on the next free port so both projects end up on distinct ports.
"""

from __future__ import annotations

import pytest

import brainpalace_cli.commands.start as start_mod

_DEFAULT_BIND = {
    "bind_host": "127.0.0.1",
    "port_range_start": 8000,
    "port_range_end": 8100,
    "auto_port": True,
}


def _stub_read_bind(bind: dict):
    return lambda sd: bind


class _AliveProc:
    def __init__(self, pid: int = 111) -> None:
        self.pid = pid

    def poll(self) -> None:
        return None


class _DeadProc:
    def __init__(self, pid: int = 222) -> None:
        self.pid = pid

    def poll(self) -> int:
        return 1


# --------------------------------------------------------------------------
# _wait_until_owned — the identity-checked wait (bug 2)
# --------------------------------------------------------------------------


def test_wait_until_owned_mine_when_own_server_answers(tmp_path):
    err = tmp_path / "server.err"
    result = start_mod._wait_until_owned(
        "http://127.0.0.1:8000",
        str(tmp_path),
        _AliveProc(),
        err,
        0,
        5,
        probe_fn=lambda url, root, timeout=2.0: "mine",
    )
    assert result == "mine"


def test_wait_until_owned_conflict_when_other_project_answers(tmp_path):
    """A DIFFERENT project answering on our port is a lost race, not success."""
    err = tmp_path / "server.err"
    result = start_mod._wait_until_owned(
        "http://127.0.0.1:8000",
        str(tmp_path),
        _AliveProc(),
        err,
        0,
        5,
        probe_fn=lambda url, root, timeout=2.0: "other",
    )
    assert result == "conflict"


def test_wait_until_owned_conflict_when_child_died_addr_in_use(tmp_path):
    """Our child exiting with EADDRINUSE is a lost race → retry elsewhere."""
    err = tmp_path / "server.err"
    err.write_text(
        "ERROR:    [Errno 98] error while attempting to bind on address "
        "('127.0.0.1', 8000): address already in use\n"
    )
    result = start_mod._wait_until_owned(
        "http://127.0.0.1:8000",
        str(tmp_path),
        _DeadProc(),
        err,
        0,
        5,
        probe_fn=lambda url, root, timeout=2.0: "down",
    )
    assert result == "conflict"


def test_wait_until_owned_raises_on_genuine_crash(tmp_path):
    """A child that died for a NON-port reason must NOT be retried — raise."""
    err = tmp_path / "server.err"
    err.write_text("Traceback (most recent call last):\n  bad provider config\n")
    with pytest.raises(RuntimeError):
        start_mod._wait_until_owned(
            "http://127.0.0.1:8000",
            str(tmp_path),
            _DeadProc(),
            err,
            0,
            5,
            probe_fn=lambda url, root, timeout=2.0: "down",
        )


def test_wait_until_owned_addr_in_use_only_reads_this_attempt(tmp_path):
    """A prior attempt's 'address already in use' below err_offset must NOT be
    mistaken for THIS child's failure (else a real crash reads as a conflict)."""
    err = tmp_path / "server.err"
    prior = "ERROR: [Errno 98] address already in use\n"
    err.write_text(prior)
    offset = err.stat().st_size
    # This attempt appended only a genuine crash, no addr-in-use.
    with err.open("a") as f:
        f.write("Traceback: KeyError 'embedding_provider'\n")
    with pytest.raises(RuntimeError):
        start_mod._wait_until_owned(
            "http://127.0.0.1:8000",
            str(tmp_path),
            _DeadProc(),
            err,
            offset,
            5,
            probe_fn=lambda url, root, timeout=2.0: "down",
        )


# --------------------------------------------------------------------------
# launch_server — end-to-end retry on a lost race (bug 1)
# --------------------------------------------------------------------------


def test_launch_server_retries_next_port_on_lost_race(tmp_path, monkeypatch):
    """The reported bug: our first-chosen port is taken by another project
    during startup; launch_server must retry the next free port, not falsely
    adopt the foreign server."""
    seq = iter([8000, 8001])
    monkeypatch.setattr(
        start_mod, "find_available_port", lambda host, start, end: next(seq)
    )

    def fake_probe(url, root, timeout=2.0):
        # 8000 is owned by ANOTHER project (we lost); 8001 is ours.
        return "mine" if url.endswith(":8001") else "other"

    monkeypatch.setattr(start_mod, "probe", fake_probe)
    monkeypatch.setattr(start_mod.subprocess, "Popen", lambda cmd, **kw: _AliveProc())
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    monkeypatch.setattr(start_mod, "read_bind", _stub_read_bind(_DEFAULT_BIND))
    monkeypatch.setattr(start_mod.os, "kill", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

    runtime = start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, timeout=5
    )
    assert runtime["port"] == 8001
    assert runtime["base_url"] == "http://127.0.0.1:8001"


def test_launch_server_explicit_port_does_not_retry_on_conflict(tmp_path, monkeypatch):
    """An explicit --port is honored exactly once: a conflict there is a hard
    error (the user asked for THAT port), never a silent scan to another."""
    monkeypatch.setattr(start_mod, "probe", lambda url, root, timeout=2.0: "other")
    monkeypatch.setattr(start_mod.subprocess, "Popen", lambda cmd, **kw: _AliveProc())
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)
    monkeypatch.setattr(start_mod, "read_bind", _stub_read_bind(_DEFAULT_BIND))
    monkeypatch.setattr(start_mod.os, "kill", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()

    with pytest.raises(RuntimeError):
        start_mod.launch_server(
            project_root=tmp_path, state_dir=state_dir, port=8080, timeout=5
        )
