"""The generated skill's frontmatter description names every query mode."""

from brainpalace_server.models.query import QueryMode

from brainpalace_cli.ai_guidance import _SKILL_FRONTMATTER


def test_frontmatter_names_all_modes():
    lower = _SKILL_FRONTMATTER.lower()
    missing = [m.value for m in QueryMode if m.value not in lower]
    assert missing == [], f"frontmatter missing modes: {missing}"
