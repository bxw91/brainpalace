"""Tests for the brainpalace update command."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands.update import (
    detect_install_manager,
    update_command,
    upgrade_argv,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestDetectInstallManager:
    """detect_install_manager classifies the binary location."""

    def test_pipx_path(self) -> None:
        path = "/home/u/.local/share/pipx/venvs/brainpalace-cli/bin/brainpalace"
        assert detect_install_manager(path) == "pipx"

    def test_uv_path(self) -> None:
        path = "/home/u/.local/share/uv/tools/brainpalace-cli/bin/brainpalace"
        assert detect_install_manager(path) == "uv"

    def test_pip_path_falls_through(self) -> None:
        path = "/home/u/.venv/bin/brainpalace"
        assert detect_install_manager(path) == "pip"

    def test_pipx_symlink_shim(self, tmp_path: Path) -> None:
        """A ~/.local/bin shim symlinked into a pipx venv classifies as pipx.

        Regression: pipx/uv put a *symlink* in ~/.local/bin; the shim path
        itself has no ``/pipx/`` segment, so classifying it verbatim misreads
        the install as bare pip (and prints a PEP 668-failing uninstall line).
        """
        venv_bin = tmp_path / ".local/share/pipx/venvs/brainpalace-cli/bin"
        venv_bin.mkdir(parents=True)
        real = venv_bin / "brainpalace"
        real.write_text("#!/usr/bin/env python\n")
        shim_dir = tmp_path / ".local/bin"
        shim_dir.mkdir(parents=True)
        shim = shim_dir / "brainpalace"
        shim.symlink_to(real)
        assert detect_install_manager(str(shim)) == "pipx"

    def test_uv_symlink_shim(self, tmp_path: Path) -> None:
        """A ~/.local/bin shim symlinked into a uv tools dir classifies as uv."""
        tool_bin = tmp_path / ".local/share/uv/tools/brainpalace-cli/bin"
        tool_bin.mkdir(parents=True)
        real = tool_bin / "brainpalace"
        real.write_text("#!/usr/bin/env python\n")
        shim_dir = tmp_path / ".local/bin"
        shim_dir.mkdir(parents=True)
        shim = shim_dir / "brainpalace"
        shim.symlink_to(real)
        assert detect_install_manager(str(shim)) == "uv"

    def test_none_when_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            assert detect_install_manager() is None


class TestUpgradeArgv:
    """upgrade_argv maps a manager to its upgrade command."""

    def test_pipx(self) -> None:
        assert upgrade_argv("pipx") == ["pipx", "upgrade", "brainpalace-cli"]

    def test_uv(self) -> None:
        assert upgrade_argv("uv") == ["uv", "tool", "upgrade", "brainpalace-cli"]

    def test_pip(self) -> None:
        assert upgrade_argv("pip") == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "brainpalace-rag",
            "brainpalace-cli",
        ]

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            upgrade_argv("brew")


class TestUpdateCommand:
    """End-to-end command behavior."""

    def test_runs_detected_upgrade(self, runner: CliRunner) -> None:
        """--yes runs the manager's upgrade argv via subprocess."""
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="pipx",
            ),
            # Keep the post-upgrade restart hermetic — nothing running.
            patch("brainpalace_cli.commands.update.running_servers", return_value=[]),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=False,
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        assert ["pipx", "upgrade", "brainpalace-cli"] in calls
        assert "upgrade complete" in result.output.lower()

    def test_unknown_manager_exits_nonzero_with_guidance(
        self, runner: CliRunner
    ) -> None:
        """When the install method can't be detected, fail with manual hint."""
        with patch(
            "brainpalace_cli.commands.update.detect_install_manager",
            return_value=None,
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code != 0
        assert "pip install --upgrade" in result.output

    def test_upgrade_failure_propagates_nonzero(self, runner: CliRunner) -> None:
        """A failing upgrade subprocess yields a non-zero exit."""

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(argv, 1)

        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="uv",
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code != 0

    def test_confirms_before_running(self, runner: CliRunner) -> None:
        """Without --yes, 'n' aborts without invoking the upgrade."""
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="pipx",
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, input="n\n")

        assert result.exit_code == 0
        assert calls == []
        assert "aborted" in result.output.lower()


class TestRestartAfterUpgrade:
    """Post-upgrade restart of running servers + the dashboard."""

    def _patches(self, manager: str, calls: list[list[str]], **extra: object):
        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        return (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value=manager,
            ),
            patch("subprocess.run", side_effect=fake_run),
        )

    def test_restarts_servers_and_dashboard_when_confirmed(
        self, runner: CliRunner
    ) -> None:
        """--yes auto-confirms; bounces each server (--no-dashboard) + dashboard."""
        calls: list[list[str]] = []
        p_mgr, p_run = self._patches("pipx", calls)
        with (
            p_mgr,
            p_run,
            patch(
                "brainpalace_cli.commands.update.running_servers",
                return_value=["/proj/a", "/proj/b"],
            ),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=True,
            ),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        subcmds = [c[1:] for c in calls]  # drop the binary/argv[0]
        # Each project server stopped then started with --no-dashboard.
        assert ["stop", "--path", "/proj/a", "--json"] in subcmds
        assert ["start", "--path", "/proj/a", "--no-dashboard", "--json"] in subcmds
        assert ["start", "--path", "/proj/b", "--no-dashboard", "--json"] in subcmds
        # Dashboard bounced exactly once.
        assert ["dashboard", "stop"] in subcmds
        assert ["dashboard", "start", "--no-open"] in subcmds

    def test_no_restart_flag_skips_and_prints_hint(self, runner: CliRunner) -> None:
        calls: list[list[str]] = []
        p_mgr, p_run = self._patches("pipx", calls)
        with (
            p_mgr,
            p_run,
            patch(
                "brainpalace_cli.commands.update.running_servers",
                return_value=["/proj/a"],
            ),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=True,
            ),
        ):
            result = runner.invoke(update_command, ["--yes", "--no-restart"])

        assert result.exit_code == 0
        subcmds = [c[1:] for c in calls]
        assert not any("stop" in s or "start" in s for s in subcmds)
        assert "restart" in result.output.lower()

    def test_decline_restart_prompt_skips(self, runner: CliRunner) -> None:
        """Without --yes, answering 'n' to the restart prompt restarts nothing."""
        calls: list[list[str]] = []
        p_mgr, p_run = self._patches("pipx", calls)
        with (
            p_mgr,
            p_run,
            patch(
                "brainpalace_cli.commands.update.running_servers",
                return_value=["/proj/a"],
            ),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=False,
            ),
        ):
            # First 'y' confirms the upgrade, then 'n' declines the restart.
            result = runner.invoke(update_command, input="y\nn\n")

        assert result.exit_code == 0
        subcmds = [c[1:] for c in calls]
        assert ["stop", "--path", "/proj/a", "--json"] not in subcmds


class TestPreflightNotice:
    """Before the upgrade runs, warn what's live (without stopping it)."""

    def test_warns_about_running_instances_before_upgrade(
        self, runner: CliRunner
    ) -> None:
        """A pre-flight line names the live servers/dashboard; nothing is
        stopped before the upgrade subprocess runs."""
        order: list[str] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            order.append("upgrade" if "upgrade" in argv else "other")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="pipx",
            ),
            patch(
                "brainpalace_cli.commands.update.running_servers",
                return_value=["/proj/a"],
            ),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=True,
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes", "--no-restart"])

        assert result.exit_code == 0
        out = result.output.lower()
        assert "heads up" in out
        assert "server" in out and "dashboard" in out
        # --no-restart means the only subprocess is the upgrade itself: the
        # pre-flight is informational, it never stops anything early.
        assert order == ["upgrade"]

    def test_silent_when_nothing_running(self, runner: CliRunner) -> None:
        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="pipx",
            ),
            patch("brainpalace_cli.commands.update.running_servers", return_value=[]),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=False,
            ),
            patch(
                "subprocess.run",
                side_effect=lambda a, **k: subprocess.CompletedProcess(a, 0),
            ),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        assert "heads up" not in result.output.lower()


class TestUpdateRegistration:
    def test_command_registered(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["update", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output
        assert "--no-restart" in result.output
