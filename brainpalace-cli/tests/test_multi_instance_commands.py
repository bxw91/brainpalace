"""Tests for multi-instance CLI commands (init, start, stop, list)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands.init import init_command
from brainpalace_cli.commands.list_cmd import list_command
from brainpalace_cli.commands.start import start_command
from brainpalace_cli.commands.stop import stop_command


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    # Create a pyproject.toml to mark it as a project root
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'\n")
    return tmp_path


class TestInitCommand:
    """Tests for the init command."""

    def test_init_creates_directory_structure(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that init creates the correct directory structure."""
        result = runner.invoke(init_command, ["--path", str(temp_project)])

        assert result.exit_code == 0
        assert "initialized successfully" in result.output.lower()

        state_dir = temp_project / ".brainpalace"
        assert state_dir.exists()
        assert (state_dir / "config.yaml").exists()
        assert not (state_dir / "config.json").exists()
        assert (state_dir / "data").exists()
        assert (state_dir / "data" / "chroma_db").exists()
        assert (state_dir / "data" / "bm25_index").exists()
        assert (state_dir / "logs").exists()

    def test_init_writes_config(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that init writes the config.yaml file with a bind: section."""
        import yaml

        result = runner.invoke(
            init_command, ["--path", str(temp_project), "--port", "9000"]
        )

        assert result.exit_code == 0

        config_path = temp_project / ".brainpalace" / "config.yaml"
        assert config_path.exists()
        config = yaml.safe_load(config_path.read_text())

        bind = config.get("bind", {})
        # --port 9000 writes port_range_start and disables auto_port.
        assert bind.get("port_range_start") == 9000
        assert bind.get("auto_port") is False

    def test_init_idempotent_when_already_initialized(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Re-running init without --force is a no-op (exit 0), not an error."""
        # First init
        runner.invoke(init_command, ["--path", str(temp_project)])

        # Second init should be a no-op success (B5: idempotent)
        result = runner.invoke(init_command, ["--path", str(temp_project)])
        assert result.exit_code == 0
        assert "already initialized" in result.output.lower()

    def test_init_force_overwrites(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that init --force overwrites existing config."""
        import yaml

        # First init with port 8000
        runner.invoke(init_command, ["--path", str(temp_project), "--port", "8000"])

        # Second init with --force and different port
        result = runner.invoke(
            init_command,
            ["--path", str(temp_project), "--port", "9000", "--force"],
        )
        assert result.exit_code == 0

        config_path = temp_project / ".brainpalace" / "config.yaml"
        assert config_path.exists()
        config = yaml.safe_load(config_path.read_text())
        assert config.get("bind", {}).get("port_range_start") == 9000

    def test_init_json_output(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that init --json outputs JSON."""
        result = runner.invoke(init_command, ["--path", str(temp_project), "--json"])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["status"] == "initialized"
        assert "project_root" in output
        assert "config" in output


class TestStartCommand:
    """Tests for the start command."""

    def test_start_fails_if_not_initialized(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that start fails if project not initialized."""
        result = runner.invoke(start_command, ["--path", str(temp_project)])

        assert result.exit_code == 1
        assert "not initialized" in result.output.lower()

    def test_start_json_error_output(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that start --json outputs JSON error."""
        result = runner.invoke(start_command, ["--path", str(temp_project), "--json"])

        assert result.exit_code == 1
        output = json.loads(result.output)
        assert "error" in output
        assert "init" in output["hint"].lower()


class TestStopCommand:
    """Tests for the stop command."""

    def test_stop_no_state_directory(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that stop handles missing state directory."""
        result = runner.invoke(stop_command, ["--path", str(temp_project)])

        assert result.exit_code == 1
        assert "no brainpalace state found" in result.output.lower()

    def test_stop_no_server_running(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that stop handles no server running."""
        # Initialize first
        runner.invoke(init_command, ["--path", str(temp_project)])

        # Stop should indicate no server running
        result = runner.invoke(stop_command, ["--path", str(temp_project)])

        # Exit code 0 since there's nothing to stop
        assert "no server running" in result.output.lower()

    def test_stop_json_output(self, runner: CliRunner, temp_project: Path) -> None:
        """Test that stop --json outputs JSON."""
        # Initialize first
        runner.invoke(init_command, ["--path", str(temp_project)])

        result = runner.invoke(stop_command, ["--path", str(temp_project), "--json"])

        output = json.loads(result.output)
        assert output["status"] == "not_running"

    def test_stop_url_resolves_project_root(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """--url maps to project_root via GET /runtime/, then proceeds."""
        # Initialize so the state dir exists for the project_root from /runtime/
        runner.invoke(init_command, ["--path", str(temp_project)])

        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = json.dumps(
            {"project_root": str(temp_project)}
        ).encode("utf-8")
        fake_resp.__enter__ = lambda self: self
        fake_resp.__exit__ = lambda self, *a: None

        with patch(
            "brainpalace_cli.commands.stop.urlopen", return_value=fake_resp
        ) as mock_urlopen:
            result = runner.invoke(
                stop_command,
                ["--url", "http://127.0.0.1:9999", "--json"],
            )

        assert mock_urlopen.called
        # Server's not actually running, so we exit "not_running" — but
        # importantly, the URL→project_root mapping worked (no exit 7).
        output = json.loads(result.output)
        assert output["status"] == "not_running"
        assert output["project_root"] == str(temp_project)

    def test_stop_url_unreachable_exits_7(self, runner: CliRunner) -> None:
        """--url with unreachable server exits 7 with connection_error."""
        with patch(
            "brainpalace_cli.commands.stop.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = runner.invoke(
                stop_command,
                ["--url", "http://127.0.0.1:9999", "--json"],
            )

        assert result.exit_code == 7
        payload = json.loads(result.output)
        assert payload["error"] == "connection_error"
        assert payload["url"] == "http://127.0.0.1:9999"


class TestListCommand:
    """Tests for the list command."""

    def test_list_no_instances(self, runner: CliRunner) -> None:
        """Test that list handles no running instances."""
        with patch("brainpalace_cli.commands.list_cmd.get_registry", return_value={}):
            result = runner.invoke(list_command)

        assert result.exit_code == 0
        assert "no running brainpalace instances found" in result.output.lower()

    def test_list_json_output(self, runner: CliRunner) -> None:
        """Test that list --json outputs JSON."""
        with patch("brainpalace_cli.commands.list_cmd.get_registry", return_value={}):
            result = runner.invoke(list_command, ["--json"])

        output = json.loads(result.output)
        assert "instances" in output
        assert output["total"] == 0

    def test_list_with_stale_instance(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """Test that list handles stale instances."""
        # Create a stale registry entry
        state_dir = temp_project / ".brainpalace"
        state_dir.mkdir(parents=True)

        # Write a runtime.json with a non-existent PID
        runtime = {
            "pid": 999999,  # Non-existent PID
            "base_url": "http://127.0.0.1:8000",
            "mode": "project",
        }
        (state_dir / "runtime.json").write_text(json.dumps(runtime))

        registry = {
            str(temp_project): {
                "state_dir": str(state_dir),
                "project_name": temp_project.name,
            }
        }

        with (
            patch(
                "brainpalace_cli.commands.list_cmd.get_registry",
                return_value=registry,
            ),
            patch(
                "brainpalace_cli.commands.list_cmd.is_process_alive",
                return_value=False,
            ),
            # Mock probe so the test is host-independent: without this it hits the
            # real network, and a server answering on 127.0.0.1:8000 returns
            # "other", skipping the entry entirely (never marked stale).
            patch(
                "brainpalace_cli.commands.list_cmd.probe",
                return_value="down",
            ),
            patch("brainpalace_cli.commands.list_cmd.save_registry"),
        ):
            result = runner.invoke(list_command, ["--all"])

        assert result.exit_code == 0
        # Should show the instance as stale
        assert "stale" in result.output.lower()


class TestCLIIntegration:
    """Integration tests for the CLI commands."""

    def test_commands_registered(self, runner: CliRunner) -> None:
        """Test that all new commands are registered."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "init" in result.output
        assert "start" in result.output
        assert "stop" in result.output
        assert "list" in result.output

    def test_init_workflow(self, runner: CliRunner, temp_project: Path) -> None:
        """Test the init workflow through the main CLI."""
        result = runner.invoke(cli, ["init", "--path", str(temp_project)])

        assert result.exit_code == 0
        assert (temp_project / ".brainpalace" / "config.yaml").exists()
        assert not (temp_project / ".brainpalace" / "config.json").exists()


class TestXdgRegistryPaths:
    """Tests for XDG path usage in registry operations."""

    def test_registry_uses_xdg_state_dir(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """update_registry writes to XDG state dir, not legacy ~/.brainpalace."""
        from brainpalace_cli.commands.start import update_registry

        project_root = tmp_path / "project"
        project_root.mkdir()
        state_dir = project_root / ".brainpalace"
        state_dir.mkdir(parents=True)

        xdg_state = tmp_path / "xdg_state" / "brainpalace"
        registry_file = xdg_state / "registry.json"

        # update_registry now delegates to the server's single locked writer,
        # which resolves its own path — patch that, not the CLI's helper.
        with patch(
            "brainpalace_server.registry.registry_path",
            return_value=registry_file,
        ):
            update_registry(project_root, state_dir)

        # Should write to XDG dir, NOT legacy
        assert registry_file.exists()
        registry = json.loads(registry_file.read_text())
        assert str(project_root) in registry

    def test_remove_registry_uses_xdg_path(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """remove_from_registry reads from XDG path via get_registry_path."""
        from brainpalace_cli.commands.stop import remove_from_registry

        project_root = tmp_path / "project"
        project_root.mkdir()

        # Create a registry at a controlled path
        xdg_registry = tmp_path / "xdg_state" / "brainpalace" / "registry.json"
        xdg_registry.parent.mkdir(parents=True)
        xdg_registry.write_text(
            json.dumps(
                {
                    str(project_root): {
                        "state_dir": str(tmp_path),
                        "project_name": "test",
                    }
                }
            )
        )

        with patch(
            "brainpalace_cli.commands.stop.get_registry_path",
            return_value=xdg_registry,
        ):
            remove_from_registry(project_root)

        # Entry should be removed
        registry = json.loads(xdg_registry.read_text())
        assert str(project_root) not in registry

    def test_start_triggers_migration(
        self, runner: CliRunner, temp_project: Path
    ) -> None:
        """start_command calls migrate_legacy_paths() early in execution."""
        # Initialize the project first
        runner.invoke(init_command, ["--path", str(temp_project)])

        with patch(
            "brainpalace_cli.commands.start.migrate_legacy_paths"
        ) as mock_migrate:
            mock_migrate.return_value = False
            # Start will fail (no actual server) but migration should be called
            runner.invoke(
                start_command,
                ["--path", str(temp_project), "--timeout", "1"],
            )
            mock_migrate.assert_called_once()

    def test_init_triggers_migration(self, runner: CliRunner, tmp_path: Path) -> None:
        """init_command calls migrate_legacy_paths() early in execution."""
        project = tmp_path / "new_project"
        project.mkdir()
        (project / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'\n")

        with patch(
            "brainpalace_cli.commands.init.migrate_legacy_paths"
        ) as mock_migrate:
            mock_migrate.return_value = False
            runner.invoke(init_command, ["--path", str(project)])
            mock_migrate.assert_called_once()


class TestProjectRootResolution:
    """Tests for project root resolution in commands."""

    def test_resolve_from_git_root(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that project root is resolved from git root."""
        # Create a fake git repo
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Create subdirectory
        sub_dir = tmp_path / "src" / "package"
        sub_dir.mkdir(parents=True)

        # Mock git rev-parse to return the tmp_path
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(tmp_path)
            mock_run.return_value = mock_result

            result = runner.invoke(init_command, ["--path", str(sub_dir)])

        # Should resolve to tmp_path (the git root)
        assert result.exit_code == 0

    def test_resolve_from_claude_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test that project root is resolved from .claude directory."""
        # Create .claude directory
        (tmp_path / ".claude").mkdir()

        # Create subdirectory
        sub_dir = tmp_path / "src"
        sub_dir.mkdir()

        # Mock git to fail (not a git repo)
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            result = runner.invoke(init_command, ["--path", str(sub_dir)])

        assert result.exit_code == 0
