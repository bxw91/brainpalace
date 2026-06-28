"""init registers the project into known_projects (dashboard fleet) on every
path — including config-only / --no-start — so it can be started from the
dashboard even when init did not start it."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod
from brainpalace_cli import known_projects


def _args(tmp_path: Path) -> list[str]:
    return [
        "--path",
        str(tmp_path),
        "--no-start",
        "--no-extract",
        "--no-sessions",
        "--no-archive",
        "--no-git-history",
        "--no-graphrag-extract",
        "--yes",
    ]


def test_init_no_start_registers_project(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    r = CliRunner().invoke(initmod.init_command, _args(tmp_path))
    assert r.exit_code == 0, r.output
    known = known_projects.load_existing()
    assert str(tmp_path.resolve()) in known
    entry = known[str(tmp_path.resolve())]
    assert entry["state_dir"] == str(tmp_path / ".brainpalace")
