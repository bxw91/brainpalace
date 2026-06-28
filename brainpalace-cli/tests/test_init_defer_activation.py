"""`brainpalace init --defer-activation` (the plugin path): configure but leave
the project NOT running, arming the ``cli.await_first_start`` activation marker.

  * bare init never writes the marker (terminal default = full autostart);
  * --defer-activation implies config-only AND writes the marker on a project
    that was never started;
  * re-running --defer-activation on an already-started project (present in the
    durable known-projects store) must NOT re-gate it (hardening item 5).
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod
from brainpalace_cli import config_schema, known_projects


def _base_args(tmp_path: Path) -> list[str]:
    return [
        "--path",
        str(tmp_path),
        "--no-extract",
        "--no-sessions",
        "--no-archive",
        "--no-git-history",
        "--no-graphrag-extract",
        "--yes",
    ]


def _run(tmp_path, monkeypatch, extra):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    return CliRunner().invoke(initmod.init_command, _base_args(tmp_path) + extra)


def test_defer_activation_arms_marker_and_skips_start(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ["--defer-activation"])
    assert r.exit_code == 0, r.output
    state = tmp_path / ".brainpalace"
    assert config_schema.read_await_first_start(state) is True
    # Implies config-only: no server step ran.
    assert "not running" in r.output.lower()


def test_bare_init_does_not_arm_marker(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, ["--no-start"])
    assert r.exit_code == 0, r.output
    assert config_schema.read_await_first_start(tmp_path / ".brainpalace") is False


def test_defer_activation_does_not_regate_started_project(tmp_path, monkeypatch):
    # Simulate a project that was already started (recorded in the fleet store).
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    known_projects.remember(tmp_path, tmp_path / ".brainpalace", tmp_path.name)
    r = _run(tmp_path, monkeypatch, ["--defer-activation"])
    assert r.exit_code == 0, r.output
    # Never re-arm a project that was already activated.
    assert config_schema.read_await_first_start(tmp_path / ".brainpalace") is False
