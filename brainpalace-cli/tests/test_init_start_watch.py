"""Tests for `brainpalace init --start` and `--watch` flags (Phase F item 2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'\n")
    return tmp_path


def _ok_result(stdout: str = "") -> MagicMock:
    r = MagicMock()
    r.returncode = 0
    r.stdout = stdout
    r.stderr = ""
    return r


class TestInitStartWatch:
    @pytest.fixture(autouse=True)
    def _skip_provider_preflight(self):
        """Bypass the --start provider pre-flight in orchestration tests.

        These tests assert subprocess orchestration only; without real API
        keys the pre-flight would abort init before any subcommand runs.
        """
        with patch("brainpalace_cli.commands.init._preflight_providers"):
            yield

    def test_no_flags_no_subprocess_called(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Without --start, init does not invoke any subcommand."""
        with patch("brainpalace_cli.commands.init.subprocess.run") as mock_run:
            result = runner.invoke(
                init_command, ["--path", str(temp_project), "--json"]
            )

        assert result.exit_code == 0
        mock_run.assert_not_called()
        payload = json.loads(result.output)
        assert payload["status"] == "initialized"
        assert payload["post_init_steps"] == []

    def test_start_flag_runs_start_subcommand(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """--start runs `brainpalace start --path <root> --json`."""
        with patch(
            "brainpalace_cli.commands.init.subprocess.run",
            return_value=_ok_result(stdout='{"status":"started"}'),
        ) as mock_run:
            result = runner.invoke(
                init_command,
                ["--path", str(temp_project), "--start", "--json"],
            )

        assert result.exit_code == 0
        assert mock_run.call_count == 1
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[:2] == ["brainpalace", "start"]
        assert "--path" in called_cmd and str(temp_project) in called_cmd
        assert "--json" in called_cmd
        payload = json.loads(result.output)
        assert payload["post_init_steps"][0]["step"] == "start"
        assert payload["post_init_steps"][0]["status"] == "ok"

    def test_start_watch_auto_runs_both_subcommands_in_order(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """--start --watch auto runs start then folders add in order."""
        with patch(
            "brainpalace_cli.commands.init.subprocess.run",
            return_value=_ok_result(),
        ) as mock_run:
            result = runner.invoke(
                init_command,
                [
                    "--path",
                    str(temp_project),
                    "--start",
                    "--watch",
                    "auto",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        assert mock_run.call_count == 2
        first = mock_run.call_args_list[0].args[0]
        second = mock_run.call_args_list[1].args[0]
        assert first[:2] == ["brainpalace", "start"]
        assert second[:3] == ["brainpalace", "folders", "add"]
        assert str(temp_project) in second
        assert "--watch" in second
        assert "auto" in second
        assert "--include-code" in second

        payload = json.loads(result.output)
        steps = payload["post_init_steps"]
        assert len(steps) == 2
        assert steps[0]["step"] == "start"
        assert steps[1]["step"] == "watch"

    def test_watch_gated_on_start_success(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """If --start fails, the watch step is NOT invoked."""
        fail = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch(
            "brainpalace_cli.commands.init.subprocess.run",
            return_value=fail,
        ) as mock_run:
            result = runner.invoke(
                init_command,
                [
                    "--path",
                    str(temp_project),
                    "--start",
                    "--watch",
                    "auto",
                    "--json",
                ],
            )

        assert result.exit_code == 1
        assert mock_run.call_count == 1  # only `start`, not folders add

    def test_rerun_with_start_on_initialized_runs_start(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """`init --start` re-run on an already-initialized project still starts.

        Regression: the already-initialized early-return skipped the --start
        pipeline, so a first run that aborted at the provider preflight could
        not be resumed without --force.
        """
        # First run: initialize only (no --start), creates config.json.
        first = runner.invoke(init_command, ["--path", str(temp_project), "--json"])
        assert first.exit_code == 0
        assert json.loads(first.output)["status"] == "initialized"

        # Second run: --start on the already-initialized project.
        with patch(
            "brainpalace_cli.commands.init.subprocess.run",
            return_value=_ok_result(stdout='{"status":"started"}'),
        ) as mock_run:
            result = runner.invoke(
                init_command,
                ["--path", str(temp_project), "--start", "--json"],
            )

        assert result.exit_code == 0
        assert mock_run.call_count == 1
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[:2] == ["brainpalace", "start"]
        payload = json.loads(result.output)
        assert payload["status"] == "initialized"
        assert payload["post_init_steps"][0]["step"] == "start"
        assert payload["post_init_steps"][0]["status"] == "ok"


class TestInitForcePreservesProviderConfig:
    """`init --force` must not clobber the user's config.yaml provider edits."""

    def test_force_preserves_existing_config_yaml(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Re-init --force keeps a user-edited config.yaml verbatim."""
        # First init to create the state dir + default config.yaml.
        runner.invoke(init_command, ["--path", str(temp_project), "--json"])
        config_yaml = temp_project / ".brainpalace" / "config.yaml"
        assert config_yaml.exists()

        # Simulate a user edit (custom provider settings).
        sentinel = "# user-edited: do-not-clobber\nembedding:\n  provider: cohere\n"
        config_yaml.write_text(sentinel)

        # Re-init with --force.
        result = runner.invoke(
            init_command, ["--path", str(temp_project), "--force", "--json"]
        )
        assert result.exit_code == 0
        assert config_yaml.read_text() == sentinel
