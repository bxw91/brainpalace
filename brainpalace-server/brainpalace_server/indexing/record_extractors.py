"""Seam #2 — pluggable record extraction. Engine ships a rule extractor;
a product registers its own without editing here."""

from __future__ import annotations

import re
from typing import Callable

from brainpalace_server.models.record import RecordCandidate

RecordExtractor = Callable[[str], list[RecordCandidate]]
_EXTRACTORS: list[RecordExtractor] = []


def register_extractor(fn: RecordExtractor) -> None:
    _EXTRACTORS.append(fn)


def reset_extractors() -> None:
    _EXTRACTORS.clear()
    _EXTRACTORS.append(rule_extract)


def extract_records(text: str) -> list[RecordCandidate]:
    out: list[RecordCandidate] = []
    for fn in _EXTRACTORS:
        try:
            out.extend(fn(text or ""))
        except Exception:
            continue
    return out


_CURRENCY = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)")


def rule_extract(text: str) -> list[RecordCandidate]:
    out: list[RecordCandidate] = []
    for m in _CURRENCY.finditer(text or ""):
        out.append(
            RecordCandidate(
                subject="amount",
                metric="amount",
                value=float(m.group(1).replace(",", "")),
                unit="USD",
            )
        )
    return out


_EXTRACTORS.append(rule_extract)
