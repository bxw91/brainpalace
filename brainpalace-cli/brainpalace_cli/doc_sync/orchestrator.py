"""Run checkers (--check) and regenerate machine-owned regions (--fix). NEVER calls
an LLM: --fix does deterministic generation and returns a `prose-needed` list for
the in-session agent to author."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import apply_rename, regenerate_command_doc
from brainpalace_cli.doc_sync.markers import MarkerError, find_block


def run_check(
    checkers: Iterable[Any], snapshot: InterfaceSnapshot
) -> tuple[int, list[DriftRecord]]:
    records: list[DriftRecord] = []
    for chk in checkers:
        records.extend(chk.check(snapshot))
    return (1 if records else 0), records


def run_fix(
    checkers: Iterable[Any], snapshot: InterfaceSnapshot
) -> list[dict[str, Any]]:
    """Deterministic regeneration. Returns prose-needed items (missing docs)."""
    prose_needed: list[dict[str, Any]] = []
    by_name = {c.name: c for c in snapshot.commands}
    fixed: set[str] = set()  # docs already regenerated this run (idempotent)
    for chk in checkers:
        for rec in chk.check(snapshot):
            if rec.kind is DriftKind.RENAME:
                old, new = rec.detail.split(" -> ", 1)
                new = new.rstrip("?").strip()
                old = old.strip()
                docs_dir = Path(rec.doc_path).parent
                if apply_rename(docs_dir, old=old, new=new) and new in by_name:
                    new_doc = docs_dir / f"brainpalace-{new}.md"
                    regenerate_command_doc(new_doc, by_name[new])
                    fixed.add(str(new_doc))
            elif rec.kind is DriftKind.MISMATCH and rec.source_id in by_name:
                regenerate_command_doc(Path(rec.doc_path), by_name[rec.source_id])
                fixed.add(rec.doc_path)
            elif rec.kind is DriftKind.MISSING:
                prose_needed.append(
                    {
                        "surface": rec.surface,
                        "id": rec.source_id,
                        "doc_path": rec.doc_path,
                        "reason": "new command needs a doc with Purpose prose",
                    }
                )
    # Migration: a flagged command whose doc is contract-clean but has no body
    # GENERATED:flags block produces no drift record (the checker allows absence),
    # so the loop above skips it. Backfill the canonical block deterministically —
    # regenerate_command_doc CREATEs it on absence and is idempotent.
    for chk in checkers:
        docs = getattr(chk, "_doc_commands", None)
        if docs is None:
            continue
        for name, path in docs().items():
            cmd = by_name.get(name)
            if cmd is None or not cmd.flags or str(path) in fixed:
                continue
            try:
                find_block(path.read_text(encoding="utf-8"), "flags")
            except MarkerError:
                regenerate_command_doc(path, cmd)
                fixed.add(str(path))
    return prose_needed


def render_report(records: list[DriftRecord]) -> str:
    if not records:
        return "doc-sync: OK"
    lines = ["doc-sync FAILED:"]
    for r in records:
        lines.append(
            f"  ✗ [{r.surface}] {r.source_id} ({r.kind.value}): "
            f"{r.detail} -> {r.doc_path}"
        )
    lines.append("\nRun `brainpalace sync-docs --fix` and commit the result.")
    return "\n".join(lines)
