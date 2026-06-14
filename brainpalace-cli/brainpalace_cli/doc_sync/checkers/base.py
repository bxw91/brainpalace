# brainpalace-cli/brainpalace_cli/doc_sync/checkers/base.py
"""Checker protocol + the shared set-diff that every surface reuses."""

from __future__ import annotations

from typing import Callable, Protocol

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot


class Checker(Protocol):
    surface: str

    def check(self, snapshot: InterfaceSnapshot) -> list[DriftRecord]: ...


def diff_sets(
    surface: str,
    live: set[str],
    docs: set[str],
    doc_path_for: Callable[[str], str],
) -> list[DriftRecord]:
    records: list[DriftRecord] = []
    for missing in sorted(live - docs):
        records.append(
            DriftRecord(
                surface,
                missing,
                doc_path_for(missing),
                DriftKind.MISSING,
                "live item has no doc",
            )
        )
    for extra in sorted(docs - live):
        records.append(
            DriftRecord(
                surface,
                extra,
                doc_path_for(extra),
                DriftKind.EXTRA,
                "doc for item that no longer exists",
            )
        )
    return records
