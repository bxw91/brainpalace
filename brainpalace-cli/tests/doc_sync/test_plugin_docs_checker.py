"""PluginDocsChecker: fail-closed registry + referential drift over the wider
plugin doc set (agents, configuring SKILL.md, references, README)."""

from __future__ import annotations

import json
from pathlib import Path

from brainpalace_cli.doc_sync.allowlist import PLUGIN_DOC_GATE_EXEMPT
from brainpalace_cli.doc_sync.checkers.plugin_docs import PluginDocsChecker
from brainpalace_cli.doc_sync.facts import CommandFact, DriftKind, InterfaceSnapshot
from brainpalace_cli.doc_sync.introspect import live_snapshot

REPO = Path(__file__).resolve().parents[3]

# A snapshot whose only live command is `query`; everything else is dangling.
SNAP = InterfaceSnapshot(1, "9.9.9", commands=[CommandFact(name="query")], modes=[])


def _plugin_tree(tmp_path: Path) -> Path:
    """Minimal plugin layout: one agent, one live skill, README."""
    pd = tmp_path / "brainpalace-plugin"
    (pd / "agents").mkdir(parents=True)
    (pd / "skills" / "using-brainpalace").mkdir(parents=True)
    (pd / "skills" / "configuring-brainpalace").mkdir(parents=True)
    (pd / "skills" / "using-brainpalace" / "SKILL.md").write_text(
        "---\nname: using-brainpalace\n---\n# using\n"
    )
    (pd / "skills" / "configuring-brainpalace" / "SKILL.md").write_text(
        "---\nname: configuring-brainpalace\n---\n# configuring\n"
    )
    (pd / "agents" / "search-assistant.md").write_text(
        "---\nname: search-assistant\n---\nRun `brainpalace query` to search.\n"
    )
    (pd / "README.md").write_text("# Plugin\nUse `brainpalace query`.\n")
    return pd


def _checker(pd: Path, tmp_path: Path, registered: set[str]) -> PluginDocsChecker:
    return PluginDocsChecker(
        plugin_dir=pd,
        repo_root=tmp_path,
        registered=registered,
        skills_dir=pd / "skills",
    )


def _all_registered(pd: Path, tmp_path: Path) -> set[str]:
    """Every scanned doc registered EXCEPT the exempt one — the clean baseline."""
    return {
        p.relative_to(tmp_path).as_posix()
        for p in pd.rglob("*.md")
        if p.relative_to(tmp_path).as_posix() not in PLUGIN_DOC_GATE_EXEMPT
    }


def test_unregistered_doc_fails_closed(tmp_path):
    pd = _plugin_tree(tmp_path)
    # Register nothing: every scanned (non-exempt) doc must be flagged MISSING.
    recs = _checker(pd, tmp_path, registered=set()).check(SNAP)
    missing = {r.source_id for r in recs if r.kind is DriftKind.MISSING}
    assert "brainpalace-plugin/agents/search-assistant.md" in missing
    assert "brainpalace-plugin/skills/configuring-brainpalace/SKILL.md" in missing
    assert "brainpalace-plugin/README.md" in missing


def test_exempt_skill_not_gated(tmp_path):
    pd = _plugin_tree(tmp_path)
    # using-brainpalace/SKILL.md is exempt → never flagged, even unregistered.
    recs = _checker(pd, tmp_path, registered=set()).check(SNAP)
    flagged = {r.source_id for r in recs}
    assert "brainpalace-plugin/skills/using-brainpalace/SKILL.md" not in flagged


def test_clean_when_registered_and_refs_live(tmp_path):
    pd = _plugin_tree(tmp_path)
    recs = _checker(pd, tmp_path, _all_registered(pd, tmp_path)).check(SNAP)
    assert recs == [], [(r.source_id, r.kind.value, r.detail) for r in recs]


def test_dangling_command_ref_flagged(tmp_path):
    pd = _plugin_tree(tmp_path)
    (pd / "agents" / "search-assistant.md").write_text(
        "---\nname: search-assistant\n---\nRun `brainpalace frobnicate` now.\n"
    )
    recs = _checker(pd, tmp_path, _all_registered(pd, tmp_path)).check(SNAP)
    # Command-ref drift reuses the cli referential scan (surface "cli") — accurate,
    # it IS a dangling CLI command; the doc_path points at the plugin doc.
    assert any(
        r.source_id == "frobnicate" and r.doc_path.endswith("search-assistant.md")
        for r in recs
    ), [(r.source_id, r.surface, r.detail) for r in recs]


def test_dangling_skill_ref_flagged(tmp_path):
    pd = _plugin_tree(tmp_path)
    (pd / "README.md").write_text("# Plugin\nSee the `gone-brainpalace` skill.\n")
    recs = _checker(pd, tmp_path, _all_registered(pd, tmp_path)).check(SNAP)
    bad = {r.source_id for r in recs}
    assert "gone-brainpalace" in bad


# --- dogfood: the gate must be GREEN against the real repo ----------------- #


def test_repo_plugin_docs_in_sync():
    registered = set(
        json.loads(
            (REPO / "scripts" / "doc_freshness.json").read_text(encoding="utf-8")
        )
    )
    recs = PluginDocsChecker(
        plugin_dir=REPO / "brainpalace-plugin",
        repo_root=REPO,
        registered=registered,
        extra_skills_dirs=(REPO / ".claude" / "skills",),
    ).check(live_snapshot())
    assert recs == [], "\n".join(
        f"{r.surface}:{r.source_id} {r.kind.value}: {r.detail}" for r in recs
    )
