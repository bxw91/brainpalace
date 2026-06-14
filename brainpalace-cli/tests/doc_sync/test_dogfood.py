from pathlib import Path

from brainpalace_cli.doc_sync.checkers.cli_commands import CliCommandsChecker
from brainpalace_cli.doc_sync.introspect import live_snapshot

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "brainpalace-plugin" / "commands"


def test_repo_command_docs_are_in_sync():
    snap = live_snapshot()
    records = CliCommandsChecker(docs_dir=DOCS).check(snap)
    assert records == [], "drift:\n" + "\n".join(
        f"{r.source_id} {r.kind.value}: {r.detail}" for r in records
    )


def test_every_command_doc_with_flags_has_a_generated_block():
    from brainpalace_cli.doc_sync.allowlist import (
        DOCUMENTED_ALIASES,
        PLUGIN_ONLY_COMMAND_DOCS,
        UNDOCUMENTED_COMMANDS,
    )

    snap = live_snapshot()
    skip = (
        set(UNDOCUMENTED_COMMANDS)
        | set(PLUGIN_ONLY_COMMAND_DOCS)
        | set(DOCUMENTED_ALIASES)
    )
    for c in snap.commands:
        if c.hidden or c.name in skip or not c.flags:
            continue
        doc = DOCS / f"brainpalace-{c.name}.md"
        assert doc.exists() and "<!--GENERATED:flags-->" in doc.read_text(), c.name


def test_modes_surface_in_sync():
    from brainpalace_cli.doc_sync.checkers.modes import ModesChecker

    docs = REPO / "brainpalace-plugin" / "commands"
    recs = ModesChecker(docs_dir=docs).check(live_snapshot())
    assert recs == [], "\n".join(
        f"{r.source_id} {r.kind.value}: {r.detail}" for r in recs
    )


def test_skills_surface_in_sync():
    from brainpalace_cli.doc_sync.checkers.skills import SkillsChecker
    from brainpalace_cli.doc_sync.introspect import live_snapshot

    docs = REPO / "brainpalace-plugin" / "commands"
    skills = REPO / "brainpalace-plugin" / "skills"
    recs = SkillsChecker(skills_dir=skills, docs_dir=docs).check(live_snapshot())
    assert recs == [], "\n".join(
        f"{r.source_id} {r.kind.value}: {r.detail}" for r in recs
    )


def test_config_mcp_endpoints_surfaces_in_sync():
    from brainpalace_cli.doc_sync.checkers.config import ConfigChecker
    from brainpalace_cli.doc_sync.checkers.endpoints import EndpointsChecker
    from brainpalace_cli.doc_sync.checkers.mcp import McpChecker
    from brainpalace_cli.doc_sync.introspect import endpoint_paths, live_snapshot

    cmds = REPO / "brainpalace-plugin" / "commands"
    docs = REPO / "docs"
    cfg_refs = (
        REPO
        / "brainpalace-plugin"
        / "skills"
        / "configuring-brainpalace"
        / "references"
    )
    snap = live_snapshot()
    snap.endpoints = endpoint_paths()
    recs = []
    recs += ConfigChecker(doc_roots=[cmds, docs, cfg_refs]).check(snap)
    recs += McpChecker(docs_dir=cmds).check(snap)
    recs += EndpointsChecker(doc_roots=[docs]).check(snap)
    assert recs == [], "\n".join(
        f"{r.surface}:{r.source_id} {r.kind.value}: {r.detail}" for r in recs
    )
