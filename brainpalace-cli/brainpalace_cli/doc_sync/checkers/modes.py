"""Modes surface: canonical GENERATED:modes block in brainpalace-query.md (add/remove
gate) + a scoped referential check for `--mode <token>` invocations elsewhere."""

from __future__ import annotations

import re
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.markers import MarkerError, find_block
from brainpalace_cli.doc_sync.referential import dangling_tokens
from brainpalace_cli.doc_sync.serializer import render_modes_table

SURFACE = "modes"
CANONICAL = "brainpalace-query.md"
# Scoped to real invocations: `--mode <tok>` or `--mode=<tok>` (resolution H).
_MODE_RE = re.compile(r"--mode[= ]([a-z][a-z0-9-]*)")


class ModesChecker:
    surface = SURFACE

    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = Path(docs_dir)

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        canon = self.docs_dir / CANONICAL
        if canon.exists():
            text = canon.read_text(encoding="utf-8")
            try:
                inner = find_block(text, "modes")
                if inner.strip() != render_modes_table(snap.modes).strip():
                    records.append(
                        DriftRecord(
                            SURFACE,
                            "query",
                            str(canon),
                            DriftKind.MISMATCH,
                            "canonical modes block out of sync with --mode Choice",
                        )
                    )
            except MarkerError:
                records.append(
                    DriftRecord(
                        SURFACE,
                        "query",
                        str(canon),
                        DriftKind.MISSING,
                        "canonical GENERATED:modes block absent",
                    )
                )
        all_docs = sorted(self.docs_dir.glob("brainpalace-*.md"))
        records.extend(
            dangling_tokens(
                all_docs,
                _MODE_RE,
                set(snap.modes),
                SURFACE,
                "`--mode {tok}` references a non-existent mode",
            )
        )
        return records
