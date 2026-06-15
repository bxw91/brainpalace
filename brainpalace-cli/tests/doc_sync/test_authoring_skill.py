from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
# Dev-only skill: repo project scope (.claude/skills), NOT the shipped plugin.
SKILL = REPO / ".claude" / "skills" / "authoring-brainpalace-docs" / "SKILL.md"


def test_skill_exists_with_valid_frontmatter():
    assert SKILL.exists()
    text = SKILL.read_text()
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["name"] == "authoring-brainpalace-docs"
    assert "last_validated" in fm


def test_skill_is_seen_by_skills_checker():
    # The dev-only skill lives outside the plugin, so SkillsChecker must pick it up
    # via extra_skills_dirs — otherwise prose/`skills:` refs to it false-positive.
    from brainpalace_cli.doc_sync.checkers.skills import SkillsChecker

    plugin_skills = REPO / "brainpalace-plugin" / "skills"
    claude_skills = REPO / ".claude" / "skills"
    live = SkillsChecker(
        skills_dir=plugin_skills,
        docs_dir=plugin_skills,
        extra_skills_dirs=[claude_skills],
    )._live_skills()
    assert "authoring-brainpalace-docs" in live
