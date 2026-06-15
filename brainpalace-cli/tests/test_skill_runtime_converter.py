"""Tests for the skill-runtime converter."""

from pathlib import Path

import pytest
import yaml

from brainpalace_cli.runtime.parser import parse_plugin_dir
from brainpalace_cli.runtime.skill_runtime_converter import (
    SkillRuntimeConverter,
    _skill_dir_name,
)
from brainpalace_cli.runtime.types import (
    PluginAgent,
    PluginBundle,
    PluginCommand,
    PluginManifest,
    PluginParameter,
    PluginScript,
    PluginSkill,
    PluginTemplate,
    RuntimeType,
    Scope,
    TriggerPattern,
)


@pytest.fixture
def sample_command() -> PluginCommand:
    return PluginCommand(
        name="brainpalace-search",
        description="Search documents",
        parameters=[
            PluginParameter(name="query", description="Search query", required=True),
            PluginParameter(
                name="top-k",
                description="Results count",
                required=False,
                default="5",
            ),
        ],
        skills=["using-brainpalace"],
        body="Run search against .claude/brainpalace data.",
    )


@pytest.fixture
def sample_agent() -> PluginAgent:
    return PluginAgent(
        name="search-assistant",
        description="Helps search documents",
        triggers=[
            TriggerPattern(pattern="search.*docs", type="message_pattern"),
        ],
        skills=["using-brainpalace"],
        body="Agent uses .claude/brainpalace for data.",
    )


@pytest.fixture
def sample_skill() -> PluginSkill:
    return PluginSkill(
        name="using-brainpalace",
        description="Search skill",
        allowed_tools=["Bash", "Read"],
        metadata={"version": "1.0.0"},
        body="Skill references .claude/brainpalace/data.",
        license="MIT",
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
        templates=[
            PluginTemplate(
                name="settings.json",
                content='{"key": "value"}',
            ),
        ],
        scripts=[
            PluginScript(
                name="bp-setup-check.sh",
                content="#!/bin/bash\necho ok",
            ),
        ],
        manifest=PluginManifest(name="brainpalace", version="9.1.0"),
    )


class TestSkillDirName:
    """Tests for skill directory naming."""

    def test_adds_prefix(self) -> None:
        assert _skill_dir_name("search") == "brainpalace-search"

    def test_preserves_existing_prefix(self) -> None:
        assert _skill_dir_name("brainpalace-search") == "brainpalace-search"


class TestSkillRuntimeConverter:
    """Tests for SkillRuntimeConverter."""

    def test_runtime_type(self) -> None:
        converter = SkillRuntimeConverter()
        assert converter.runtime_type == RuntimeType.SKILL_RUNTIME

    def test_convert_command_produces_valid_skill(
        self, sample_command: PluginCommand
    ) -> None:
        converter = SkillRuntimeConverter()
        result = converter.convert_command(sample_command)
        # Parse frontmatter
        parts = result.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "brainpalace-search"
        assert fm["description"] == "Search documents"
        assert "Bash" in fm["allowed-tools"]
        # Path replacement
        assert ".claude/brainpalace" not in result
        assert ".brainpalace" in result

    def test_convert_command_includes_parameters(
        self, sample_command: PluginCommand
    ) -> None:
        converter = SkillRuntimeConverter()
        result = converter.convert_command(sample_command)
        assert "## Parameters" in result
        assert "**query**" in result
        assert "(required)" in result
        assert "[default: 5]" in result

    def test_convert_command_no_parameters(self) -> None:
        cmd = PluginCommand(
            name="brainpalace-status",
            description="Check status",
            body="Check the status.",
        )
        converter = SkillRuntimeConverter()
        result = converter.convert_command(cmd)
        assert "## Parameters" not in result

    def test_convert_agent_produces_orchestration_skill(
        self, sample_agent: PluginAgent
    ) -> None:
        converter = SkillRuntimeConverter()
        result = converter.convert_agent(sample_agent)
        parts = result.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "search-assistant"
        assert "Grep" in fm["allowed-tools"]
        assert "Orchestration skill" in result
        assert "using-brainpalace" in result
        assert ".claude/brainpalace" not in result

    def test_convert_skill_preserves_format(self, sample_skill: PluginSkill) -> None:
        converter = SkillRuntimeConverter()
        result = converter.convert_skill(sample_skill)
        parts = result.split("---\n")
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "using-brainpalace"
        assert fm["allowed-tools"] == ["Bash", "Read"]
        assert fm["license"] == "MIT"
        assert ".claude/brainpalace" not in result

    def test_install_creates_skill_directories(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        converter = SkillRuntimeConverter()
        target = tmp_path / "skills"
        files = converter.install(sample_bundle, target, Scope.PROJECT)

        # Commands
        assert (target / "brainpalace-search" / "SKILL.md").exists()
        # Agents
        assert (target / "brainpalace-search-assistant" / "SKILL.md").exists()
        # Skills
        assert (target / "brainpalace-using-brainpalace" / "SKILL.md").exists()
        # Templates
        assert (target / "brainpalace-setup" / "SKILL.md").exists()
        assert (target / "brainpalace-setup" / "assets" / "settings.json").exists()
        # Scripts
        assert (target / "brainpalace-verify" / "SKILL.md").exists()
        assert (
            target / "brainpalace-verify" / "scripts" / "bp-setup-check.sh"
        ).exists()

        # Check all files are tracked
        assert len(files) >= 7  # 3 skills + setup + settings + verify + script

    def test_install_skill_md_has_valid_frontmatter(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        converter = SkillRuntimeConverter()
        target = tmp_path / "skills"
        converter.install(sample_bundle, target, Scope.PROJECT)

        # Check every SKILL.md has valid YAML frontmatter
        for skill_md in target.rglob("SKILL.md"):
            content = skill_md.read_text()
            assert content.startswith("---\n")
            parts = content.split("---\n")
            fm = yaml.safe_load(parts[1])
            assert "name" in fm
            assert "description" in fm

    def test_install_with_references(self, tmp_path: Path) -> None:
        """Test that skill references are copied."""
        skill = PluginSkill(
            name="using-brainpalace",
            description="Search skill",
            allowed_tools=["Bash", "Read"],
            body="Skill body.",
        )
        # Create a source skill dir with references
        src_dir = tmp_path / "source" / "skills" / "using-brainpalace"
        src_dir.mkdir(parents=True)
        skill_file = src_dir / "SKILL.md"
        skill_file.write_text("---\nname: using-brainpalace\n---\nBody.")
        refs_dir = src_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide")
        skill.source_path = str(skill_file)

        bundle = PluginBundle(skills=[skill])
        converter = SkillRuntimeConverter()
        target = tmp_path / "output"
        files = converter.install(bundle, target, Scope.PROJECT)

        refs_out = target / "brainpalace-using-brainpalace" / "references"
        assert refs_out.is_dir()
        assert (refs_out / "guide.md").exists()
        assert any("guide.md" in str(f) for f in files)

    def test_install_no_templates_or_scripts(self, tmp_path: Path) -> None:
        """Test that setup/verify dirs are not created without templates/scripts."""
        bundle = PluginBundle(
            commands=[
                PluginCommand(
                    name="brainpalace-status",
                    description="Status check",
                    body="Check.",
                ),
            ],
        )
        converter = SkillRuntimeConverter()
        target = tmp_path / "output"
        converter.install(bundle, target, Scope.PROJECT)
        assert not (target / "brainpalace-setup").exists()
        assert not (target / "brainpalace-verify").exists()

    def test_dry_run_via_tempdir(
        self, tmp_path: Path, sample_bundle: PluginBundle
    ) -> None:
        """Test that dry-run pattern works (install to tempdir, remap)."""
        import tempfile

        converter = SkillRuntimeConverter()
        real_target = tmp_path / "real-target"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_target = Path(tmp)
            files = converter.install(sample_bundle, tmp_target, Scope.PROJECT)
            planned = [real_target / f.relative_to(tmp_target) for f in files]

        # Real target should not exist
        assert not real_target.exists()
        # Planned files should reference real target
        assert all(str(f).startswith(str(real_target)) for f in planned)
        assert len(planned) >= 7


class TestSkillRuntimeRoundTrip:
    """Round-trip tests: parse real plugin → convert → verify."""

    @pytest.fixture
    def real_plugin_dir(self) -> Path | None:
        path = Path(__file__).parent.parent.parent / "brainpalace-plugin"
        if path.is_dir():
            return path
        return None

    def test_real_plugin_produces_skill_dirs(
        self, real_plugin_dir: Path | None, tmp_path: Path
    ) -> None:
        if real_plugin_dir is None:
            pytest.skip("Real plugin dir not found")
        bundle = parse_plugin_dir(real_plugin_dir)
        converter = SkillRuntimeConverter()
        target = tmp_path / "skills"
        files = converter.install(bundle, target, Scope.PROJECT)

        # Should produce skill dirs for all commands + agents + skills
        expected_count = len(bundle.commands) + len(bundle.agents) + len(bundle.skills)
        skill_dirs = [d for d in target.iterdir() if d.is_dir()]
        # At least expected_count dirs (plus setup/verify if templates/scripts)
        assert len(skill_dirs) >= expected_count

        # Every skill dir should have SKILL.md
        for skill_dir in skill_dirs:
            assert (
                skill_dir / "SKILL.md"
            ).exists(), f"Missing SKILL.md in {skill_dir.name}"

        # Templates should be in setup/assets
        if bundle.templates:
            assert (target / "brainpalace-setup" / "assets").is_dir()

        # Scripts should be in verify/scripts
        if bundle.scripts:
            assert (target / "brainpalace-verify" / "scripts").is_dir()

        # Total files should be substantial
        assert len(files) >= 30, f"Expected 30+ files, got {len(files)}"

    def test_all_skill_mds_have_valid_frontmatter(
        self, real_plugin_dir: Path | None, tmp_path: Path
    ) -> None:
        if real_plugin_dir is None:
            pytest.skip("Real plugin dir not found")
        bundle = parse_plugin_dir(real_plugin_dir)
        converter = SkillRuntimeConverter()
        target = tmp_path / "skills"
        converter.install(bundle, target, Scope.PROJECT)

        for skill_md in target.rglob("SKILL.md"):
            content = skill_md.read_text()
            assert content.startswith("---\n"), f"Invalid frontmatter in {skill_md}"
            parts = content.split("---\n")
            fm = yaml.safe_load(parts[1])
            assert "name" in fm, f"Missing name in {skill_md}"
            assert "description" in fm, f"Missing description in {skill_md}"
