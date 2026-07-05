"""Modes surface: canonical GENERATED:modes block in brainpalace-query.md (add/remove
gate) + a scoped referential check for `--mode <token>` invocations elsewhere +
MODE_META coverage + any additional per-doc `targets` (README/docs mode tables in
their own richer shape, e.g. README's grid or USER_GUIDE's commands table)."""

from __future__ import annotations

import re
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import MODES_RENDERERS
from brainpalace_cli.doc_sync.markers import MarkerError, find_block
from brainpalace_cli.doc_sync.mode_meta import MODE_META
from brainpalace_cli.doc_sync.referential import dangling_tokens
from brainpalace_cli.doc_sync.serializer import render_modes_table

SURFACE = "modes"
CANONICAL = "brainpalace-query.md"
# Scoped to real invocations: `--mode <tok>` or `--mode=<tok>` (resolution H).
_MODE_RE = re.compile(r"--mode[= ]([a-z][a-z0-9-]*)")


class ModesChecker:
    surface = SURFACE

    def __init__(self, docs_dir: Path, targets: dict[Path, str] | None = None) -> None:
        self.docs_dir = Path(docs_dir)
        # path -> style ("table"/"grid"/"commands"): additional docs whose own
        # GENERATED:modes block (if present) is checked against that doc's style.
        self.targets = {Path(p): style for p, style in (targets or {}).items()}

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        missing_meta = [m for m in snap.modes if m not in MODE_META]
        if missing_meta:
            records.append(
                DriftRecord(
                    SURFACE,
                    "mode-meta",
                    "brainpalace_cli/doc_sync/mode_meta.py",
                    DriftKind.MISSING,
                    f"MODE_META has no entry for live mode(s): {missing_meta!r}",
                )
            )
        # A mode lacking MODE_META already yields a MISSING record above; every
        # render_modes_* call raises ValueError for it, so skip the render-based
        # comparisons below rather than crash the whole checker on that gap.
        canon = self.docs_dir / CANONICAL
        if canon.exists():
            text = canon.read_text(encoding="utf-8")
            try:
                inner = find_block(text, "modes")
                if (
                    not missing_meta
                    and inner.strip() != render_modes_table(snap.modes).strip()
                ):
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
        if not missing_meta:
            for path, style in self.targets.items():
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8")
                try:
                    inner = find_block(text, "modes")
                except MarkerError:
                    continue  # block not present in this doc — nothing to gate
                render = MODES_RENDERERS[style]
                if inner.strip() != render(snap.modes).strip():
                    records.append(
                        DriftRecord(
                            SURFACE,
                            path.stem,
                            str(path),
                            DriftKind.MISMATCH,
                            f"GENERATED:modes block ({style}) out of sync with "
                            "--mode Choice",
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
