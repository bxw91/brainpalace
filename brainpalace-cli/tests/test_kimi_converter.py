"""Tests for the Kimi CLI runtime converter.

Mirrors test_antigravity_converter.py — KimiConverter is architecturally a
thin SkillInstructionConverter subclass (same as Codex/Antigravity), so its
test coverage should match theirs, adjusted for the Kimi target directory
(.kimi-code/skills/brainpalace, a researched project-subdir assumption —
Kimi MCP separately writes to ~/.kimi/) and header text. Like Codex, Kimi's
instruction file is AGENTS.md.
"""

import json
from pathlib import Path

import pytest
import yaml

from brainpalace_cli.runtime.kimi_converter import KimiConverter
from brainpalace_cli.runtime.skill_instruction_converter import (
    INSTRUCTION_FILE_END,
    INSTRUCTION_FILE_START,
)
from brainpalace_cli.runtime.types import (
    PluginAgent,
    PluginBundle,
    PluginCommand,
    PluginManifest,
    PluginParameter,
    PluginSkill,
    RuntimeType,
    Scope,
)


@pytest.fixture
def sample_command() -> PluginCommand:
    return PluginCommand(
        name="brainpalace-search",
        description="Search documents",
        parameters=[
            PluginParameter(name="query", description="Search query", required=True),
        ],
        skills=["using-brainpalace"],
        body="Run search against .claude/brainpalace data.",
    )


@pytest.fixture
def sample_agent() -> PluginAgent:
    return PluginAgent(
        name="search-assistant",
        description="Helps search documents",
        triggers=[],
        skills=["using-brainpalace"],
        body="Agent body.",
    )


@pytest.fixture
def sample_skill() -> PluginSkill:
    return PluginSkill(
        name="using-brainpalace",
        description="Search skill",
        allowed_tools=["Bash", "Read"],
        body="Skill body.",
    )


@pytest.fixture
def sample_bundle(
    sample_command: PluginCommand,
    sample_agent: PluginAgent,
    sample_skill: PluginSkill,
) -> PluginBundle:
    return PluginBundle(
        commands=[sample_command],
        agents=[sample_agent],
        skills=[sample_skill],
        manifest=PluginManifest(name="brainpalace", version="9.1.0"),
    )


class TestKimiConverter:
    """Tests for KimiConverter."""

    def test_runtime_type(self) -> None:
        converter = KimiConverter()
        assert converter.runtime_type == RuntimeType.KIMI

    def test_convert_command_has_kimi_header(
        self, sample_command: PluginCommand
    ) -> None:
        converter = KimiConverter()
        result = converter.convert_command(sample_command)
        assert "Kimi Skill:" in result
        assert "brainpalace-search" in result

    def test_convert_agent_has_kimi_header(self, sample_agent: PluginAgent) -> None:
        converter = KimiConverter()
        result = converter.convert_agent(sample_agent)
        assert "Kimi Skill:" in result
        assert "search-assistant" in result

    def test_convert_skill_preserves_format(self, sample_skill: PluginSkill) -> None:
        converter = KimiConverter()
        result = converter.convert_skill(sample_skill)
        parts = result.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "using-brainpalace"
        assert fm["allowed-tools"] == ["Bash", "Read"]

    def test_install_creates_kimi_structure(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        """Test Kimi install creates skills + AGENTS.md under .kimi-code/."""
        # Simulate project layout: tmp_path is project root
        target = tmp_path / ".kimi-code" / "skills" / "brainpalace"
        converter = KimiConverter()
        files = converter.install(sample_bundle, target, Scope.PROJECT)

        # Skills should exist
        assert (target / "brainpalace-search" / "SKILL.md").exists()
        assert (target / "brainpalace-search-assistant" / "SKILL.md").exists()
        assert (target / "brainpalace-using-brainpalace" / "SKILL.md").exists()

        # AGENTS.md should be created at project root
        agents_md = tmp_path / "AGENTS.md"
        assert agents_md.exists()
        assert agents_md in files

    def test_install_agents_md_content(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        """Test AGENTS.md contains correct content."""
        target = tmp_path / ".kimi-code" / "skills" / "brainpalace"
        converter = KimiConverter()
        converter.install(sample_bundle, target, Scope.PROJECT)

        agents_md = tmp_path / "AGENTS.md"
        content = agents_md.read_text()
        assert INSTRUCTION_FILE_START in content
        assert INSTRUCTION_FILE_END in content
        assert "BrainPalace" in content
        assert "brainpalace-search" in content
        assert "search-assistant" in content
        assert "using-brainpalace" in content

    def test_install_kimi_headers_in_skills(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        """Test that command/agent SKILL.md files have Kimi headers."""
        target = tmp_path / ".kimi-code" / "skills" / "brainpalace"
        converter = KimiConverter()
        converter.install(sample_bundle, target, Scope.PROJECT)

        cmd_skill = (target / "brainpalace-search" / "SKILL.md").read_text()
        assert "Kimi Skill:" in cmd_skill

        agent_skill = (target / "brainpalace-search-assistant" / "SKILL.md").read_text()
        assert "Kimi Skill:" in agent_skill

    def test_install_idempotent(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        """Running install twice should not duplicate the AGENTS.md section."""
        target = tmp_path / ".kimi-code" / "skills" / "brainpalace"
        converter = KimiConverter()
        converter.install(sample_bundle, target, Scope.PROJECT)
        first_content = (tmp_path / "AGENTS.md").read_text()

        converter.install(sample_bundle, target, Scope.PROJECT)
        second_content = (tmp_path / "AGENTS.md").read_text()

        assert first_content == second_content
        assert second_content.count(INSTRUCTION_FILE_START) == 1
        assert second_content.count(INSTRUCTION_FILE_END) == 1


class TestKimiDryRun:
    """Tests for Kimi dry-run + install via install_agent command."""

    @pytest.fixture
    def plugin_dir(self, tmp_path: Path) -> Path:
        """Create minimal plugin directory."""
        root = tmp_path / "plugin"
        root.mkdir()
        manifest = root / ".claude-plugin"
        manifest.mkdir()
        (manifest / "plugin.json").write_text(
            json.dumps({"name": "brainpalace", "version": "1.0.0"})
        )
        cmds = root / "commands"
        cmds.mkdir()
        (cmds / "brainpalace-search.md").write_text(
            "---\nname: brainpalace-search\n"
            "description: Search\nparameters: []\nskills: []\n"
            "---\nBody."
        )
        agents = root / "agents"
        agents.mkdir()
        (agents / "search-assistant.md").write_text(
            "---\nname: search-assistant\n"
            "description: Helper\ntriggers: []\nskills: []\n"
            "---\nBody."
        )
        skills = root / "skills" / "using-brainpalace"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text(
            "---\nname: using-brainpalace\n"
            "description: Skill\nallowed-tools: [Bash]\n"
            "---\nBody."
        )
        return root

    def test_kimi_dry_run(self, tmp_path: Path, plugin_dir: Path) -> None:
        """Test --agent kimi --dry-run via CLI runner."""
        from click.testing import CliRunner

        from brainpalace_cli.commands.install_agent import (
            install_agent_command,
        )

        runner = CliRunner()
        result = runner.invoke(
            install_agent_command,
            [
                "--agent",
                "kimi",
                "--plugin-dir",
                str(plugin_dir),
                "--path",
                str(tmp_path),
                "--dry-run",
                "--json",
            ],
        )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["dry_run"] is True
        assert output["agent"] == "kimi"
        assert output["file_count"] > 0

    def test_kimi_install(self, tmp_path: Path, plugin_dir: Path) -> None:
        """Test --agent kimi installs to .kimi-code/skills/brainpalace + AGENTS.md."""
        from click.testing import CliRunner

        from brainpalace_cli.commands.install_agent import (
            install_agent_command,
        )

        runner = CliRunner()
        result = runner.invoke(
            install_agent_command,
            [
                "--agent",
                "kimi",
                "--plugin-dir",
                str(plugin_dir),
                "--path",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        target = tmp_path / ".kimi-code" / "skills" / "brainpalace"
        assert target.is_dir()
        assert (target / "brainpalace-search" / "SKILL.md").exists()
        assert (tmp_path / "AGENTS.md").exists()
