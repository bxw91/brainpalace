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


@pytest.fixture(autouse=True)
def _hermetic_reapers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep restart tests from touching real processes: the orphan reaper and
    the process-scan default to no-ops. Tests that assert reaping override them.

    Also neutralize the post-upgrade plugin flow. It reads the live Claude Code
    registry and fetches the latest plugin version from GitHub, so on a host with
    the plugin installed AND a newer plugin release available it fires a real
    ``claude plugin update`` subprocess — making these update-ordering/restart
    tests pass or fail by host state (exactly the trap docs/RELEASING.md step 8
    flags). The plugin flow has its own tests in test_plugin_version.py.
    """
    monkeypatch.setattr(
        "brainpalace_cli.commands.update._reap_orphan_servers", lambda: None
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.update._dashboard_orphan_pids", lambda: []
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.update._plugin_update_flow", lambda *a, **k: None
    )


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
        assert upgrade_argv("pipx") == [
            "pipx",
            "upgrade",
            "brainpalace-cli",
            "--pip-args=--no-cache-dir",
        ]

    def test_uv(self) -> None:
        assert upgrade_argv("uv") == [
            "uv",
            "tool",
            "upgrade",
            "--no-cache",
            "brainpalace-cli",
        ]

    def test_pip(self) -> None:
        assert upgrade_argv("pip") == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
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
        assert [
            "pipx",
            "upgrade",
            "brainpalace-cli",
            "--pip-args=--no-cache-dir",
        ] in calls
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
        # Dashboard bounced exactly once (start with --json to capture the URL).
        assert ["dashboard", "stop"] in subcmds
        assert ["dashboard", "start", "--no-open", "--json"] in subcmds

    def test_dashboard_restart_shows_url_panel(self, runner: CliRunner) -> None:
        """After bouncing the dashboard, `update` prints the URL panel (parity
        with `start` / `dashboard start`)."""

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "dashboard" in argv and "start" in argv:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=(
                        '{"status": "started", '
                        '"base_url": "http://127.0.0.1:8787/dashboard/"}'
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with (
            patch(
                "brainpalace_cli.commands.update.detect_install_manager",
                return_value="pipx",
            ),
            patch("brainpalace_cli.commands.update.running_servers", return_value=[]),
            patch(
                "brainpalace_cli.commands.update.dashboard_running", return_value=True
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        assert "Web Dashboard" in result.output
        assert "8787/dashboard" in result.output

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

    def test_decline_prompt_aborts_without_stopping_or_upgrading(
        self, runner: CliRunner
    ) -> None:
        """One combined consent. Declining it stops nothing and upgrades nothing."""
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
            result = runner.invoke(update_command, input="n\n")

        assert result.exit_code == 0
        # Nothing ran at all — no stop, no upgrade.
        assert calls == []
        assert "aborted" in result.output.lower()

    def test_orphan_dashboards_trigger_cleanup_restart(self, runner: CliRunner) -> None:
        """No registry servers and a stale pidfile, but a stray dashboard is
        live (process scan) — the upgrade still bounces the dashboard so the
        orphan is reaped via `dashboard stop`."""
        calls: list[list[str]] = []
        p_mgr, p_run = self._patches("pipx", calls)
        with (
            p_mgr,
            p_run,
            patch("brainpalace_cli.commands.update.running_servers", return_value=[]),
            patch(
                "brainpalace_cli.commands.update.dashboard_running",
                return_value=False,
            ),
            # A leaked dashboard the pidfile no longer tracks.
            patch(
                "brainpalace_cli.commands.update._dashboard_orphan_pids",
                return_value=[8123],
            ),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        subcmds = [c[1:] for c in calls]
        assert ["dashboard", "stop"] in subcmds
        assert ["dashboard", "start", "--no-open", "--json"] in subcmds

    def test_reaps_orphan_servers_before_restart(self, runner: CliRunner) -> None:
        """The upgrade reaps non-registry server duplicates before restarting."""
        calls: list[list[str]] = []
        reaped: list[bool] = []
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
            patch(
                "brainpalace_cli.commands.update._reap_orphan_servers",
                side_effect=lambda: reaped.append(True),
            ),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        assert reaped == [True]


class TestUpdateOrdering:
    """Default flow stops everything *before* the upgrade; --no-restart doesn't."""

    @staticmethod
    def _classify(argv: list[str]) -> str:
        if "upgrade" in argv and "brainpalace-cli" in argv:
            return "upgrade"
        if "stop" in argv or ("dashboard" in argv and "stop" in argv):
            return "stop"
        if "start" in argv:
            return "start"
        return "other"

    def test_default_stops_all_before_upgrade(self, runner: CliRunner) -> None:
        """A stop for the live server + dashboard precedes the upgrade subprocess."""
        order: list[str] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            order.append(self._classify(argv))
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
                "brainpalace_cli.commands.update.dashboard_running", return_value=True
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code == 0
        # Every stop happens before the upgrade; every start happens after it.
        up = order.index("upgrade")
        assert "stop" in order[:up]
        assert all(order.index(x) > up for x in order if x == "start")

    def test_upgrade_failure_after_stop_warns_loudly(self, runner: CliRunner) -> None:
        """If the upgrade fails after everything was stopped, the user is told
        loudly that nothing runs and they are NOT on the new version."""

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            rc = 1 if ("upgrade" in argv and "brainpalace-cli" in argv) else 0
            return subprocess.CompletedProcess(argv, rc, stdout="", stderr="boom")

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
                "brainpalace_cli.commands.update.dashboard_running", return_value=True
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes"])

        assert result.exit_code != 0
        out = result.output.lower()
        assert "not on the new version" in out
        assert "brainpalace start" in out

    def test_no_restart_does_not_stop_and_warns_old_code(
        self, runner: CliRunner
    ) -> None:
        """--no-restart upgrades only; instances keep running old code (warned)."""
        order: list[str] = []

        def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            order.append(self._classify(argv))
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
                "brainpalace_cli.commands.update.dashboard_running", return_value=True
            ),
            patch("subprocess.run", side_effect=fake_run),
        ):
            result = runner.invoke(update_command, ["--yes", "--no-restart"])

        assert result.exit_code == 0
        assert order == ["upgrade"]  # nothing stopped or started
        assert "old code" in result.output.lower()

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


class TestStopAllInstancesVerification:
    """`_stop_all_instances` must VERIFY death and escalate to SIGKILL — a
    fire-and-forget SIGTERM let the upgrade run while old code was still alive."""

    def _patch_survivors(
        self, monkeypatch: pytest.MonkeyPatch, sequence: list[tuple[list, list]]
    ) -> None:
        """Make `_live_survivors` return each entry of `sequence` in turn (last
        value sticks), so a test can script 'alive, then dead'."""
        from itertools import chain, repeat

        it = chain(sequence, repeat(sequence[-1]))
        monkeypatch.setattr(
            "brainpalace_cli.commands.update._live_survivors", lambda: next(it)
        )

    def test_returns_true_when_stop_takes_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from brainpalace_cli.commands import update as u

        monkeypatch.setattr(u, "_issue_stops", lambda *a, **k: None)
        self._patch_survivors(monkeypatch, [([], [])])
        killed: list[int] = []
        monkeypatch.setattr(u, "_sigkill_pids", lambda pids: killed.extend(pids))

        assert u._stop_all_instances([], argv=["bp"], home="/tmp") is True
        assert killed == []  # nothing alive → never escalate

    def test_escalates_to_sigkill_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from brainpalace_cli.commands import update as u

        monkeypatch.setattr(u, "_issue_stops", lambda *a, **k: None)
        monkeypatch.setattr(u, "_STOP_GRACE_SECS", 0.0)
        monkeypatch.setattr(u, "_STOP_KILL_GRACE_SECS", 0.0)
        monkeypatch.setattr(u, "_server_pids", lambda roots: [4242])
        # alive after SIGTERM, dead after SIGKILL.
        self._patch_survivors(monkeypatch, [(["/proj"], []), ([], [])])
        killed: list[int] = []
        monkeypatch.setattr(u, "_sigkill_pids", lambda pids: killed.extend(pids))

        assert u._stop_all_instances(["/proj"], argv=["bp"], home="/tmp") is True
        assert killed == [4242]  # escalated

    def test_yes_warns_and_continues_when_sigkill_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from brainpalace_cli.commands import update as u

        monkeypatch.setattr(u, "_issue_stops", lambda *a, **k: None)
        monkeypatch.setattr(u, "_STOP_GRACE_SECS", 0.0)
        monkeypatch.setattr(u, "_STOP_KILL_GRACE_SECS", 0.0)
        monkeypatch.setattr(u, "_server_pids", lambda roots: [99])
        monkeypatch.setattr(u, "_sigkill_pids", lambda pids: None)
        # never dies.
        self._patch_survivors(monkeypatch, [(["/proj"], [7])])

        # --yes must not prompt and must return False (proceeding with survivors).
        assert (
            u._stop_all_instances(["/proj"], argv=["bp"], home="/tmp", yes=True)
            is False
        )


class TestUpdateRegistration:
    def test_command_registered(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["update", "--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output
        assert "--no-restart" in result.output
