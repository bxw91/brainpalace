"""Tests for the mono-repo workspace-root guard on `brainpalace init`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def monorepo_root(tmp_path: Path) -> Path:
    """A directory whose CLAUDE.md flags it as a mono-repo workspace root."""
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='ws'\n")
    (tmp_path / "CLAUDE.md").write_text(
        "# Workspace Structure\n\n"
        "This is a mono-repo workspace. Independent projects live under "
        "`projects/`.\n\n"
        "Do not treat the workspace root as a project. It is an "
        "organisational container only.\n"
    )
    return tmp_path


@pytest.fixture
def normal_project(tmp_path: Path) -> Path:
    """A regular project: pyproject + a normal CLAUDE.md."""
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='proj'\n")
    (tmp_path / "CLAUDE.md").write_text("# My Project\n\nNormal project notes here.\n")
    return tmp_path


class TestMonorepoGuard:
    def test_monorepo_root_refused_by_default(
        self, runner: CliRunner, monorepo_root: Path
    ) -> None:
        result = runner.invoke(init_command, ["--path", str(monorepo_root), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "monorepo_root_refused"
        # state dir must NOT have been created
        assert not (monorepo_root / ".brainpalace").exists()

    def test_force_monorepo_root_proceeds(
        self, runner: CliRunner, monorepo_root: Path
    ) -> None:
        result = runner.invoke(
            init_command,
            ["--path", str(monorepo_root), "--force-monorepo-root", "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "initialized"
        assert (monorepo_root / ".brainpalace").is_dir()

    def test_normal_project_unaffected(
        self, runner: CliRunner, normal_project: Path
    ) -> None:
        result = runner.invoke(init_command, ["--path", str(normal_project), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "initialized"
        assert (normal_project / ".brainpalace").is_dir()

    def test_project_without_claude_md_unaffected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='p'\n")
        result = runner.invoke(init_command, ["--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        assert (tmp_path / ".brainpalace").is_dir()
