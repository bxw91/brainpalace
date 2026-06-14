"""`sync-docs` (check/fix) + `dump-interface` (introspection). Deterministic; no LLM.
Both hidden — maintenance commands, not user-facing (see allowlist)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from brainpalace_cli.doc_sync.checkers.cli_commands import CliCommandsChecker
from brainpalace_cli.doc_sync.checkers.config import ConfigChecker
from brainpalace_cli.doc_sync.checkers.endpoints import EndpointsChecker
from brainpalace_cli.doc_sync.checkers.mcp import CANONICAL as MCP_CANONICAL
from brainpalace_cli.doc_sync.checkers.mcp import McpChecker
from brainpalace_cli.doc_sync.checkers.modes import CANONICAL as MODES_CANONICAL
from brainpalace_cli.doc_sync.checkers.modes import ModesChecker
from brainpalace_cli.doc_sync.checkers.skills import SkillsChecker
from brainpalace_cli.doc_sync.generator import (
    regenerate_mcp_tools,
    regenerate_query_modes,
)
from brainpalace_cli.doc_sync.introspect import (
    dump_interface_json,
    endpoint_paths,
    live_snapshot,
)
from brainpalace_cli.doc_sync.orchestrator import render_report, run_check, run_fix

# Plugin command docs live in the repo; resolved relative to repo root at runtime.
# parents[3] of .../brainpalace_cli/commands/sync_docs.py == the monorepo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_DIR = _REPO_ROOT / "brainpalace-plugin" / "commands"
_SKILLS_DIR = _REPO_ROOT / "brainpalace-plugin" / "skills"
_DOCS = _REPO_ROOT / "docs"
_CFG_REFS = _SKILLS_DIR / "configuring-brainpalace" / "references"


def _checkers() -> list[Any]:
    return [
        CliCommandsChecker(docs_dir=_DOCS_DIR),
        ModesChecker(docs_dir=_DOCS_DIR),
        SkillsChecker(skills_dir=_SKILLS_DIR, docs_dir=_DOCS_DIR),
        ConfigChecker(doc_roots=[_DOCS_DIR, _DOCS, _CFG_REFS]),
        McpChecker(docs_dir=_DOCS_DIR),
        EndpointsChecker(doc_roots=[_DOCS]),
    ]


@click.command("dump-interface", hidden=True)
@click.option(
    "--include-endpoints",
    is_flag=True,
    help="Also introspect FastAPI routes and include them in the snapshot.",
)
def dump_interface_command(include_endpoints: bool) -> None:
    """Emit a versioned JSON snapshot of the live interface (CLI surface)."""
    import json as _json

    payload = _json.loads(dump_interface_json())
    if include_endpoints:
        payload["endpoints"] = endpoint_paths()
    click.echo(_json.dumps(payload, indent=2, sort_keys=True), nl=False)


@click.command("sync-docs", hidden=True)
@click.option(
    "--check", "mode_check", is_flag=True, help="Report drift, exit 1 if any."
)
@click.option(
    "--fix",
    "mode_fix",
    is_flag=True,
    help="Regenerate machine-owned regions; print prose-needed.",
)
def sync_docs_command(mode_check: bool, mode_fix: bool) -> None:
    """Keep interface docs in sync with live code.

    Deterministic; never calls an LLM.
    """
    snap = live_snapshot()
    snap.endpoints = endpoint_paths()  # opt-in: endpoints checker needs them
    checkers = _checkers()
    if mode_fix:
        regenerate_query_modes(_DOCS_DIR / MODES_CANONICAL, snap.modes)
        regenerate_mcp_tools(_DOCS_DIR / MCP_CANONICAL, snap.mcp_tools)
        prose_needed = run_fix(checkers, snap)
        for item in prose_needed:
            click.echo(
                f"PROSE-NEEDED: {item['id']} -> {item['doc_path']} "
                f"({item['reason']})"
            )
    code, records = run_check(checkers, snap)
    click.echo(render_report(records))
    raise SystemExit(code)
