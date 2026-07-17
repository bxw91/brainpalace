"""A4 (HIGH severity) — `stop` must never kill a different project's server.

Regression cover for the copy-scenario incident: a copied ``.brainpalace/``
carries the ORIGINAL project's pid + base_url in its ``runtime.json``. Before
this fix, ``brainpalace stop`` in the copy would SIGTERM the pid straight out
of runtime.json — killing the ORIGINAL project's live server. The fix probes
``/health/`` for identity (``project_root``) before ever signalling the pid.

See ``.planning/specs/2026-07-13-identity-checked-server-health.md`` (A4).
"""

from __future__ import annotations

import json
import os

from click.testing import CliRunner

import brainpalace_cli.commands.stop as stop_mod


def _make_project(tmp_path, name: str, *, pid: int, base_url: str):
    project_root = tmp_path / name
    state_dir = project_root / ".brainpalace"
    state_dir.mkdir(parents=True)
    (state_dir / stop_mod.RUNTIME_FILE).write_text(
        json.dumps(
            {
                "pid": pid,
                "base_url": base_url,
                "project_root": str(project_root),
            }
        )
    )
    (state_dir / stop_mod.PID_FILE).write_text(str(pid))
    (state_dir / stop_mod.LOCK_FILE).write_text("")
    return project_root, state_dir


def test_stop_in_copy_does_not_kill_original_server(tmp_path, monkeypatch):
    """`stop` in a copy whose runtime.json points at the original's live
    server must NOT SIGTERM that pid — it must recognize "other" and only
    clean up its own local state."""
    shared_pid = os.getpid()  # any "alive" pid; must never actually be signalled
    shared_url = "http://127.0.0.1:8000"

    original_root, original_state = _make_project(
        tmp_path, "original", pid=shared_pid, base_url=shared_url
    )
    copy_root, copy_state = _make_project(
        tmp_path, "copy", pid=shared_pid, base_url=shared_url
    )

    killed: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))

    monkeypatch.setattr(stop_mod.os, "kill", fake_kill)
    monkeypatch.setattr(stop_mod, "is_process_alive", lambda _pid: True)

    def fake_probe(base_url: str, expected_root, timeout: float = 3.0) -> str:
        # Only the "copy" project's own root resolves to "mine"; anything else
        # asking about this shared base_url is "other".
        from pathlib import Path

        return "mine" if Path(expected_root) == original_root else "other"

    monkeypatch.setattr(stop_mod, "probe", fake_probe)

    result = CliRunner().invoke(
        stop_mod.stop_command, ["--path", str(copy_root), "--json"]
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "not_running_here"

    # The pid was NEVER signalled — the original keeps running.
    assert killed == []

    # The copy's own local state was cleaned up.
    assert not (copy_state / stop_mod.RUNTIME_FILE).exists()
    assert not (copy_state / stop_mod.PID_FILE).exists()
    assert not (copy_state / stop_mod.LOCK_FILE).exists()

    # The original's runtime.json is untouched.
    assert (original_state / stop_mod.RUNTIME_FILE).exists()


def test_stop_kills_own_server_when_identity_matches(tmp_path, monkeypatch):
    """Sanity check: when probe confirms "mine", stop proceeds to SIGTERM as
    before (guards against the fix over-blocking the normal path)."""
    pid = 424242
    project_root, state_dir = _make_project(
        tmp_path, "solo", pid=pid, base_url="http://127.0.0.1:8001"
    )

    killed: list[tuple[int, int]] = []

    def fake_kill(kill_pid: int, sig: int) -> None:
        killed.append((kill_pid, sig))
        raise ProcessLookupError  # simulate immediate graceful exit

    monkeypatch.setattr(stop_mod.os, "kill", fake_kill)
    monkeypatch.setattr(
        stop_mod,
        "is_process_alive",
        lambda check_pid: check_pid == pid and len(killed) == 0,
    )
    monkeypatch.setattr(stop_mod, "probe", lambda *_a, **_k: "mine")

    result = CliRunner().invoke(
        stop_mod.stop_command, ["--path", str(project_root), "--json"]
    )

    assert result.exit_code == 0, result.output
    import signal as signal_mod

    assert killed == [(pid, signal_mod.SIGTERM)]
    output = json.loads(result.output)
    assert output["status"] == "stopped"
