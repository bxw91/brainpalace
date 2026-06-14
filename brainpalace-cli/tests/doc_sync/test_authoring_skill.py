from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SKILL = (
    REPO / "brainpalace-plugin" / "skills" / "authoring-brainpalace-docs" / "SKILL.md"
)


def test_skill_exists_with_valid_frontmatter():
    assert SKILL.exists()
    text = SKILL.read_text()
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["name"] == "authoring-brainpalace-docs"
    assert "last_validated" in fm


def test_skill_is_seen_by_skills_checker():
    # The new skill must be discoverable so SkillsChecker can validate refs to it.
    from brainpalace_cli.doc_sync.checkers.skills import SkillsChecker

    skills = REPO / "brainpalace-plugin" / "skills"
    live = SkillsChecker(skills_dir=skills, docs_dir=skills)._live_skills()
    assert "authoring-brainpalace-docs" in live
