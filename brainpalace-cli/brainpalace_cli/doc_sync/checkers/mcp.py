# brainpalace-cli/brainpalace_cli/doc_sync/checkers/mcp.py
"""MCP surface: canonical GENERATED:mcp-tools block in brainpalace-mcp.md.

A broad prose tool-name scan is intentionally omitted: unscoped snake_case
matching false-positives on every `read_only`/`api_key` token. The canonical
generated block is the real completeness + drift gate.
"""

from __future__ import annotations

from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.markers import MarkerError, find_block
from brainpalace_cli.doc_sync.serializer import render_mcp_tools_table

SURFACE = "mcp"
CANONICAL = "brainpalace-mcp.md"


class McpChecker:
    surface = SURFACE

    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = Path(docs_dir)

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        canon = self.docs_dir / CANONICAL
        if canon.exists():
            text = canon.read_text(encoding="utf-8")
            try:
                inner = find_block(text, "mcp-tools")
                if inner.strip() != render_mcp_tools_table(snap.mcp_tools).strip():
                    records.append(
                        DriftRecord(
                            SURFACE,
                            "mcp",
                            str(canon),
                            DriftKind.MISMATCH,
                            "canonical mcp-tools block out of sync",
                        )
                    )
            except MarkerError:
                records.append(
                    DriftRecord(
                        SURFACE,
                        "mcp",
                        str(canon),
                        DriftKind.MISSING,
                        "canonical GENERATED:mcp-tools block absent",
                    )
                )
        return records
