import textwrap

from brainpalace_cli.doc_sync.checkers.skills import SkillsChecker
from brainpalace_cli.doc_sync.facts import DriftKind, InterfaceSnapshot


def _skills(tmp_path, *names):
    sd = tmp_path / "skills"
    for n in names:
        (sd / n).mkdir(parents=True)
        (sd / n / "SKILL.md").write_text(f"---\nname: {n}\n---\n# {n}\n")
    return sd


def _cmd_doc(docs, name, skills_yaml):
    (docs).mkdir(parents=True, exist_ok=True)
    (docs / f"brainpalace-{name}.md").write_text(
        textwrap.dedent(
            f"""\
        ---
        name: brainpalace-{name}
        skills:
        {skills_yaml}
        ---
        # {name}
        """
        )
    )


SNAP = InterfaceSnapshot(1, "9.9.9", commands=[], modes=[])


def test_frontmatter_skill_must_exist(tmp_path):
    sd = _skills(tmp_path, "using-brainpalace")
    docs = tmp_path / "commands"
    _cmd_doc(docs, "query", "  - dead-brainpalace")
    recs = SkillsChecker(skills_dir=sd, docs_dir=docs).check(SNAP)
    assert any(
        r.source_id == "dead-brainpalace" and r.kind is DriftKind.EXTRA for r in recs
    )


def test_valid_frontmatter_skill_clean(tmp_path):
    sd = _skills(tmp_path, "using-brainpalace")
    docs = tmp_path / "commands"
    _cmd_doc(docs, "query", "  - using-brainpalace")
    recs = SkillsChecker(skills_dir=sd, docs_dir=docs).check(SNAP)
    assert recs == []


def test_prose_dangling_skill_ref_scoped_to_convention(tmp_path):
    sd = _skills(tmp_path, "using-brainpalace")
    docs = tmp_path / "commands"
    _cmd_doc(docs, "query", "  - using-brainpalace")
    (docs / "brainpalace-x.md").write_text(
        "---\nname: x\n---\nSee the `gone-brainpalace` skill. This skill is fine.\n"
    )
    recs = SkillsChecker(skills_dir=sd, docs_dir=docs).check(SNAP)
    bad = {r.source_id for r in recs}
    assert "gone-brainpalace" in bad  # matches *-brainpalace convention, not live
    assert "This" not in bad and "skill" not in bad  # 'this skill' not flagged
