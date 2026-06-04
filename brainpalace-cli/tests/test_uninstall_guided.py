"""Tests for the guided-uninstall helper functions and command flow."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.uninstall import (
    discover_mcp_configs,
    discover_plugin_dirs,
    package_uninstall_plan,
    parse_selection,
    remaining_steps_message,
    remove_mcp_entry,
    uninstall_command,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestParseSelection:
    """parse_selection turns a user string into 0-based indices."""

    def test_all(self) -> None:
        assert parse_selection("all", 3) == [0, 1, 2]

    def test_space_separated(self) -> None:
        assert parse_selection("1 3", 3) == [0, 2]

    def test_range(self) -> None:
        assert parse_selection("1-3", 4) == [0, 1, 2]

    def test_comma_separated(self) -> None:
        assert parse_selection("2,4", 5) == [1, 3]

    def test_blank_is_empty(self) -> None:
        assert parse_selection("", 3) == []

    def test_drops_out_of_range_and_garbage(self) -> None:
        assert parse_selection("9 x 2", 3) == [1]

    def test_dedupes_preserving_order(self) -> None:
        assert parse_selection("2 1 2", 3) == [1, 0]


class TestDiscoverPluginDirs:
    """discover_plugin_dirs finds existing plugin install dirs."""

    def test_finds_global_and_project(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        gl = home / ".claude" / "plugins" / "brainpalace"
        gl.mkdir(parents=True)
        proj = tmp_path / "proj"
        pp = proj / ".opencode" / "plugins" / "brainpalace"
        pp.mkdir(parents=True)

        found = discover_plugin_dirs([proj], home=home)

        assert gl in found
        assert pp in found

    def test_skips_absent(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        found = discover_plugin_dirs([], home=home)
        assert found == []


class TestRemoveMcpEntry:
    """remove_mcp_entry surgically strips the brainpalace server entry."""

    def test_removes_json_entry_keeps_others(self, tmp_path: Path) -> None:
        cfg = tmp_path / ".vscode" / "mcp.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            json.dumps(
                {
                    "servers": {
                        "brainpalace": {"command": "x"},
                        "other": {"command": "y"},
                    }
                }
            )
        )

        changed = remove_mcp_entry(cfg, "json", "servers")

        assert changed is True
        data = json.loads(cfg.read_text())
        assert "brainpalace" not in data["servers"]
        assert "other" in data["servers"]
        # A backup was written next to the file.
        assert list(cfg.parent.glob("mcp.json.bak.*"))

    def test_no_entry_returns_false_no_backup(self, tmp_path: Path) -> None:
        cfg = tmp_path / ".cursor" / "mcp.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"mcpServers": {"other": {}}}))

        changed = remove_mcp_entry(cfg, "json", "mcpServers")

        assert changed is False
        assert not list(cfg.parent.glob("mcp.json.bak.*"))

    def test_yaml_list_shape(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        import yaml

        cfg = tmp_path / ".continue" / "mcp.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            yaml.safe_dump({"mcpServers": [{"name": "brainpalace"}, {"name": "keep"}]})
        )

        changed = remove_mcp_entry(cfg, "yaml", "mcpServers")

        assert changed is True
        data = yaml.safe_load(cfg.read_text())
        names = [s["name"] for s in data["mcpServers"]]
        assert names == ["keep"]


class TestDiscoverMcpConfigs:
    """discover_mcp_configs returns existing config files under each base."""

    def test_finds_existing(self, tmp_path: Path) -> None:
        base = tmp_path / "proj"
        vs = base / ".vscode" / "mcp.json"
        vs.parent.mkdir(parents=True)
        vs.write_text("{}")

        found = discover_mcp_configs([base])
        paths = [p for (p, _fmt, _key) in found]
        assert vs in paths


class TestPackageUninstallPlan:
    """package_uninstall_plan maps a manager to (mode, argv)."""

    def test_pipx_exec(self) -> None:
        assert package_uninstall_plan("pipx") == (
            "exec",
            ["pipx", "uninstall", "brainpalace-cli"],
        )

    def test_uv_exec(self) -> None:
        assert package_uninstall_plan("uv") == (
            "exec",
            ["uv", "tool", "uninstall", "brainpalace-cli"],
        )

    def test_pip_manual(self) -> None:
        mode, argv = package_uninstall_plan("pip")
        assert mode == "manual"
        assert argv == [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "brainpalace-rag",
            "brainpalace-cli",
            "-y",
        ]

    def test_unknown(self) -> None:
        assert package_uninstall_plan(None) == ("unknown", [])


class TestRemainingStepsMessage:
    """remaining_steps_message lists the manual leftovers."""

    def test_pip_includes_command_and_rc(self) -> None:
        mode, argv = package_uninstall_plan("pip")
        msg = remaining_steps_message("pip", mode, argv)
        assert "pip uninstall" in msg
        assert "API key" in msg or "_API_KEY" in msg

    def test_pip_notes_pep668_fallback(self) -> None:
        """PEP 668 hint: a bare pip uninstall is refused on Debian/Ubuntu
        system Python; the message must point at --break-system-packages."""
        mode, argv = package_uninstall_plan("pip")
        msg = remaining_steps_message("pip", mode, argv)
        assert "--break-system-packages" in msg

    def test_pipx_only_rc_reminder(self) -> None:
        mode, argv = package_uninstall_plan("pipx")
        msg = remaining_steps_message("pipx", mode, argv)
        assert "pip uninstall" not in msg
        assert "API key" in msg or "_API_KEY" in msg

    def test_cc_marketplace_plugin_listed_in_leftovers(self) -> None:
        """The Claude Code marketplace plugin is surfaced in the final block."""
        from pathlib import Path

        mode, argv = package_uninstall_plan("pipx")
        plugin = Path("/home/u/.claude/plugins/cache/mkt/brainpalace")
        msg = remaining_steps_message("pipx", mode, argv, [plugin])
        assert str(plugin) in msg
        assert "/plugin" in msg
        # plugin note comes before the API-key reminder
        assert msg.index("/plugin") < msg.index("_API_KEY")

    def test_no_cc_marketplace_plugin_no_plugin_lines(self) -> None:
        """Without a detected plugin, no /plugin guidance is printed."""
        mode, argv = package_uninstall_plan("pipx")
        msg = remaining_steps_message("pipx", mode, argv, [])
        assert "/plugin" not in msg
        assert "marketplace plugin" not in msg


class TestGuidedCommandFlow:
    """End-to-end guided teardown via the no-flag command."""

    def test_full_flow_pip(self, runner: CliRunner, tmp_path: Path) -> None:
        """Answers yes to each step; pip manager → prints leftover pip line."""
        proj = tmp_path / "proj"
        state_dir = proj / ".brainpalace"
        state_dir.mkdir(parents=True)
        registry = tmp_path / "registry.json"
        registry.write_text(
            json.dumps(
                {str(proj): {"state_dir": str(state_dir), "project_name": "proj"}}
            )
        )

        plugin_dir = tmp_path / "home" / ".claude" / "plugins" / "brainpalace"
        plugin_dir.mkdir(parents=True)

        mcp = proj / ".vscode" / "mcp.json"
        mcp.parent.mkdir(parents=True)
        mcp.write_text(json.dumps({"servers": {"brainpalace": {}, "keep": {}}}))

        xdg_config = tmp_path / "config" / "brainpalace"
        xdg_config.mkdir(parents=True)
        xdg_state = tmp_path / "state" / "brainpalace"
        xdg_state.mkdir(parents=True)
        legacy = tmp_path / ".brainpalace"

        with (
            patch(
                "brainpalace_cli.commands.uninstall.get_registry_path",
                return_value=registry,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_plugin_dirs",
                return_value=[plugin_dir],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_mcp_configs",
                return_value=[(mcp, "json", "servers")],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_config_dir",
                return_value=xdg_config,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_state_dir",
                return_value=xdg_state,
            ),
            patch("brainpalace_cli.commands.uninstall.LEGACY_DIR", new=legacy),
            patch(
                "brainpalace_cli.commands.uninstall.detect_install_manager",
                return_value="pip",
            ),
        ):
            # stop? / plugins? / mcp? / which projects / global?
            result = runner.invoke(uninstall_command, input="y\ny\ny\n1\ny\n")

        assert result.exit_code == 0
        assert not plugin_dir.exists()
        assert "brainpalace" not in json.loads(mcp.read_text())["servers"]
        assert not state_dir.exists()
        assert not xdg_config.exists()
        assert "pip uninstall" in result.output

    def test_exec_path_pipx(self, runner: CliRunner, tmp_path: Path) -> None:
        """pipx manager → offers to exec the package uninstall as final act."""
        registry = tmp_path / "registry.json"  # does not exist → empty
        execed: list[list[str]] = []

        with (
            patch(
                "brainpalace_cli.commands.uninstall.get_registry_path",
                return_value=registry,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_plugin_dirs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_mcp_configs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_config_dir",
                return_value=tmp_path / "nope1",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_state_dir",
                return_value=tmp_path / "nope2",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.LEGACY_DIR",
                new=tmp_path / "nope3",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.detect_install_manager",
                return_value="pipx",
            ),
            patch(
                "brainpalace_cli.commands.uninstall._exec_package",
                side_effect=lambda argv: execed.append(argv),
            ),
        ):
            result = runner.invoke(uninstall_command, input="y\n")

        assert result.exit_code == 0
        assert ["pipx", "uninstall", "brainpalace-cli"] in execed

    def test_cc_plugin_notice_printed_at_end(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """The Claude Code plugin notice appears in the final leftovers block,
        after the global-state step — not interrupting the teardown mid-flow."""
        cc_plugin = (
            tmp_path / "home" / ".claude" / "plugins" / "cache" / "mkt" / "brainpalace"
        )
        cc_plugin.mkdir(parents=True)
        registry = tmp_path / "registry.json"  # empty → no servers/state
        xdg_config = tmp_path / "config" / "brainpalace"
        xdg_config.mkdir(parents=True)

        with (
            patch(
                "brainpalace_cli.commands.uninstall.get_registry_path",
                return_value=registry,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_plugin_dirs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_cc_marketplace_plugin",
                return_value=[cc_plugin],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_mcp_configs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_config_dir",
                return_value=xdg_config,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_state_dir",
                return_value=tmp_path / "state" / "brainpalace",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.LEGACY_DIR",
                new=tmp_path / ".brainpalace",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.detect_install_manager",
                return_value=None,  # unknown → no exec prompt, message printed
            ),
        ):
            result = runner.invoke(uninstall_command, input="y\n")  # global? yes

        assert result.exit_code == 0
        out = result.output
        # The plugin notice is present, inside the final leftovers block.
        # (The long path itself is soft-wrapped by rich, so assert on the stable
        # guidance tokens rather than the contiguous path string.)
        assert "Remaining steps (optional / manual)" in out
        assert "marketplace plugin" in out
        assert "/plugin" in out
        # ...and the block appears AFTER the global-state step (i.e. at the end),
        # not interrupting the teardown mid-flow.
        assert out.index("Global state:") < out.index("Remaining steps")
        assert out.index("Remaining steps") < out.index("marketplace plugin")

    def test_guided_skip_keeps_global(self, runner: CliRunner, tmp_path: Path) -> None:
        """Answering 'n' to the global prompt leaves global state intact."""
        registry = tmp_path / "registry.json"  # empty
        xdg_config = tmp_path / "config" / "brainpalace"
        xdg_config.mkdir(parents=True)

        with (
            patch(
                "brainpalace_cli.commands.uninstall.get_registry_path",
                return_value=registry,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_plugin_dirs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.discover_mcp_configs",
                return_value=[],
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_config_dir",
                return_value=xdg_config,
            ),
            patch(
                "brainpalace_cli.commands.uninstall.get_xdg_state_dir",
                return_value=tmp_path / "state" / "brainpalace",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.LEGACY_DIR",
                new=tmp_path / ".brainpalace",
            ),
            patch(
                "brainpalace_cli.commands.uninstall.detect_install_manager",
                return_value=None,
            ),
        ):
            result = runner.invoke(uninstall_command, input="n\n")

        assert result.exit_code == 0
        assert xdg_config.exists()
