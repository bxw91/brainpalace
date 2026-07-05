"""Adapt the query_modes contract-parity result into doc-sync DriftRecords so the
lint:doc-sync gate fails on any cross-surface mode drift (both directions)."""

from __future__ import annotations

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.mode_parity import query_modes_mismatches

_SURFACE_LOCATOR = {
    "cli_choice": "brainpalace_cli/commands/query.py (--mode Choice)",
    "mcp_literal": "brainpalace_cli/mcp_server/schemas.py (QueryMode)",
    "hook_guard": "brainpalace_cli/commands/hook.py (_GUARD_QUERY_MODES)",
    "mode_meta": "brainpalace_cli/doc_sync/mode_meta.py (MODE_META)",
    "<sot>": "brainpalace_server/models/query.py (QueryMode)",
}


class ModeParityChecker:
    surface = "mode-parity"

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        for m in query_modes_mismatches():
            path = _SURFACE_LOCATOR.get(m.surface, m.surface)
            if m.error is not None:
                msg = f"{m.surface}: extractor error: {m.error}"
            else:
                msg = (
                    f"{m.surface} out of sync with server QueryMode enum: "
                    f"missing={sorted(m.missing)} extra={sorted(m.extra)}"
                )
            records.append(
                DriftRecord(self.surface, m.surface, path, DriftKind.MISMATCH, msg)
            )
        return records
