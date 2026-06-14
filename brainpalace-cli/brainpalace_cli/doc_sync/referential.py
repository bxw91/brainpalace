"""Generic dangling-token scan: flag references whose captured token is not in a
known set. Scoped by the caller's regex (resolution H — scope to real references,
not any prose mention)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord


def dangling_tokens(
    docs: Sequence[Path | str],
    pattern: re.Pattern[str],
    known: set[str],
    surface: str,
    detail: str,
) -> list[DriftRecord]:
    records: list[DriftRecord] = []
    for path in docs:
        text = Path(path).read_text(encoding="utf-8")
        seen: set[str] = set()
        for m in pattern.finditer(text):
            tok = m.group(1)
            if tok in known or tok in seen:
                continue
            seen.add(tok)
            records.append(
                DriftRecord(
                    surface,
                    tok,
                    str(path),
                    DriftKind.EXTRA,
                    detail.format(tok=tok),
                )
            )
    return records
