"""Regenerate the machine-owned regions of a command doc from a CommandFact:
the frontmatter `parameters:` block and the GENERATED:flags table. Body prose and
all non-contract frontmatter keys are preserved verbatim."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from brainpalace_cli.doc_sync.facts import CommandFact, InterfaceSnapshot
from brainpalace_cli.doc_sync.markers import (
    CLOSE,
    OPEN_FMT,
    MarkerError,
    find_block,
    replace_block,
)
from brainpalace_cli.doc_sync.serializer import (
    render_flags_section,
    render_flags_table,
    render_mcp_tools_table,
    render_modes_table,
    render_params_yaml,
)

_PARAMS_RE = re.compile(r"^parameters:.*?(?=^\S|\Z)", re.MULTILINE | re.DOTALL)


def apply_rename(docs_dir: Path, old: str, new: str) -> bool:
    """git mv brainpalace-<old>.md -> brainpalace-<new>.md, preserving the OLD doc's
    prose, ONLY when the new stub carries `renamed_from: <old>`. Returns False (no-op)
    when the hint is absent. Never deletes prose; never runs in CI (caller gates)."""
    old_doc = docs_dir / f"brainpalace-{old}.md"
    new_doc = docs_dir / f"brainpalace-{new}.md"
    if not new_doc.exists():
        return False
    new_text = new_doc.read_text(encoding="utf-8")
    if f"renamed_from: {old}" not in new_text:
        return False
    if not old_doc.exists():
        return False
    # Carry the OLD doc's full content (prose), rename its `name:`, drop any hint.
    body = old_doc.read_text(encoding="utf-8")
    # count=1: only the frontmatter `name:` line, never a prose mention of the token.
    body = body.replace(f"name: brainpalace-{old}", f"name: brainpalace-{new}", 1)
    body = re.sub(r"^renamed_from:.*\n", "", body, flags=re.MULTILINE)
    # Drop the stub from index+worktree so `git mv` has a clear destination, then
    # move the old doc into its place (preserves rename in history) and write body.
    subprocess.run(
        ["git", "rm", "-f", str(new_doc)], cwd=docs_dir, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "mv", str(old_doc), str(new_doc)],
        cwd=docs_dir,
        check=True,
        capture_output=True,
    )
    new_doc.write_text(body, encoding="utf-8")
    return True


def _replace_params_frontmatter(text: str, cmd: CommandFact) -> str:
    if not text.startswith("---"):
        raise ValueError("doc has no frontmatter")
    head, fm, body = text.split("---", 2)
    new_params = render_params_yaml(cmd)
    if _PARAMS_RE.search(fm):
        fm = _PARAMS_RE.sub(new_params + "\n", fm, count=1)
    else:
        fm = fm.rstrip("\n") + "\n" + new_params + "\n"
    return "---" + fm + "---" + body


def regenerate_command_doc(path: Path, cmd: CommandFact) -> None:
    text = path.read_text(encoding="utf-8")
    text = _replace_params_frontmatter(text, cmd)
    if cmd.flags:
        try:
            find_block(text, "flags")
            text = replace_block(text, "flags", render_flags_table(cmd))
        except MarkerError:
            # No block yet: CREATE one by appending a Flags section to the body.
            text = text.rstrip("\n") + "\n\n" + render_flags_section(cmd) + "\n"
    path.write_text(text, encoding="utf-8")


def regenerate_mcp_tools(path: Path, tools: list[str]) -> None:
    """Refresh (or create) the canonical GENERATED:mcp-tools block in an MCP doc."""
    text = path.read_text(encoding="utf-8")
    table = render_mcp_tools_table(tools)
    try:
        find_block(text, "mcp-tools")
        text = replace_block(text, "mcp-tools", table)
    except MarkerError:
        text = (
            text.rstrip("\n")
            + "\n\n## MCP Tools\n"
            + f"{OPEN_FMT.format(name='mcp-tools')}\n{table}\n{CLOSE}\n"
        )
    path.write_text(text, encoding="utf-8")


def regenerate_query_modes(path: Path, modes: list[str]) -> None:
    """Refresh (or create) the canonical GENERATED:modes block in query.md."""
    text = path.read_text(encoding="utf-8")
    table = render_modes_table(modes)
    try:
        find_block(text, "modes")
        text = replace_block(text, "modes", table)
    except MarkerError:
        text = (
            text.rstrip("\n")
            + "\n\n## Modes\n"
            + f"{OPEN_FMT.format(name='modes')}\n{table}\n{CLOSE}\n"
        )
    path.write_text(text, encoding="utf-8")


def regenerate_provider_tables(path: Path, snap: InterfaceSnapshot) -> bool:
    """Refresh every provider/install GENERATED block PRESENT in ``path`` from the
    live registry. Only existing blocks are rewritten (these tables are placed by a
    human where they belong, never auto-appended). Returns True if the file changed.
    """
    from brainpalace_cli.doc_sync.checkers.provider_tables import GENERATED_RENDERERS

    text = path.read_text(encoding="utf-8")
    original = text
    for name, render in GENERATED_RENDERERS.items():
        if OPEN_FMT.format(name=name) not in text:
            continue
        try:
            text = replace_block(text, name, render(snap))
        except MarkerError:
            continue  # malformed markers — the checker reports it as INVALID
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False
