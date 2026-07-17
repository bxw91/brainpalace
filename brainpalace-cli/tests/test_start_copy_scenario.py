"""A1/A6 — end-to-end copy scenario: `start` in a copied folder must launch
its OWN server, never silently bind to the original's.

Regression cover for the incident this spec fixes: a copied ``.brainpalace/``
carries the ORIGINAL project's ``runtime.json`` (same pid, same base_url —
the original's live, healthy server). Before this fix, a bare pid-alive +
bare-200 health check made `start` in the copy report "already running" and
never regenerate its own runtime.json. Now the reuse gate is identity-checked
via ``probe()``: the copy's probe resolves to "other" (a different project
answered at that base_url), so `classify_existing_server` returns "stale" and
`start` cleans up + launches its own fresh server on a distinct port.

See ``.planning/specs/2026-07-13-identity-checked-server-health.md`` (A1, A6).
"""

from __future__ import annotations

import json
import os

from click.testing import CliRunner

import brainpalace_cli.commands.start as start_mod


def _make_copied_project(tmp_path, name: str, *, pid: int, base_url: str):
    """A project folder whose runtime.json/pid/lock were copied verbatim from
    the original — i.e. it points at the ORIGINAL's live server."""
    project_root = tmp_path / name
    state_dir = project_root / ".brainpalace"
    state_dir.mkdir(parents=True)
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "auto_port": True})
    )
    (state_dir / start_mod.RUNTIME_FILE).write_text(
        json.dumps(
            {
                "pid": pid,
                "base_url": base_url,
                # Copied verbatim: still says the ORIGINAL's project_root.
                "project_root": str(tmp_path / "original"),
            }
        )
    )
    (state_dir / start_mod.LOCK_FILE).write_text("")
    return project_root, state_dir


def test_start_in_copy_launches_own_server_instead_of_reusing_original(
    tmp_path, monkeypatch
):
    """The copy's stale/foreign runtime.json must NOT short-circuit start —
    it must be cleaned up and a fresh server launched for the copy."""
    shared_pid = os.getpid()  # alive; the original's real server pid
    shared_url = "http://127.0.0.1:8000"  # the original's live, healthy server

    copy_root, copy_state = _make_copied_project(
        tmp_path, "copy", pid=shared_pid, base_url=shared_url
    )

    launched: dict[str, object] = {}

    def fake_launch(*, project_root, state_dir, **kwargs):
        launched["project_root"] = project_root
        launched["state_dir"] = state_dir
        return {
            "base_url": "http://127.0.0.1:8001",  # a DISTINCT, fresh port
            "pid": 999999,
            "log_file": str(state_dir / "logs" / "server.log"),
        }

    def fake_probe(base_url: str, expected_root, timeout: float = 3.0) -> str:
        # The copy asks about its own root; the shared base_url actually
        # belongs to the "original" project, so the copy always sees "other".
        return "other"

    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)
    monkeypatch.setattr(start_mod, "probe", fake_probe)
    monkeypatch.setattr(start_mod, "find_reusable_server", lambda _p: None)
    monkeypatch.setattr(start_mod, "launch_server", fake_launch)
    monkeypatch.setattr(start_mod, "_ensure_dashboard", lambda **_k: None)

    result = CliRunner().invoke(start_mod.start_command, ["--path", str(copy_root)])

    assert result.exit_code == 0, result.output
    # A fresh server was launched FOR THE COPY — never reused the original's.
    assert launched.get("project_root") == copy_root
    assert launched.get("state_dir") == copy_state
    assert "8001" in result.output  # the fresh, distinct port
    assert "already running" not in result.output.lower()
