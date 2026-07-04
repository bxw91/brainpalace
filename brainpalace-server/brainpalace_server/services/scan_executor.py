"""Phase 2 — deterministic map-reduce over the session archive (no LLM).

Counts occurrences of one tokenized term/phrase across archived transcripts,
bucketed by ISO week / month / day / source tool. Pure file IO + the BM25
per-language analyzers — no embeddings, no network, no server state. The
caller (query_service) owns gating (archive on?) and threading
(asyncio.to_thread).

Contract: answers are over the RETAINED archive — retention/eviction shifts
results (documented in docs/SCAN.md).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date
from pathlib import Path

from brainpalace_server.indexing.session_loader import load_session
from brainpalace_server.indexing.text_analysis import get_analyzer
from brainpalace_server.services.scan_compiler import ScanPlan

logger = logging.getLogger(__name__)

#: Archive day-folder: YYYY-MM-DD-<tool> (tool suffix optional for tolerance).
_DAY_DIR = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(.+))?$")


def _bucket(day: str, tool: str, group_by: str | None) -> str | None:
    if group_by == "week":
        iso = date.fromisoformat(day).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if group_by == "month":
        return day[:7]
    if group_by == "day":
        return day
    if group_by == "source":
        return tool
    return None


def _count_occurrences(tokens: list[str], needle: list[str]) -> int:
    """Non-overlapping occurrences of the needle token sequence."""
    n = len(needle)
    if n == 0 or n > len(tokens):
        return 0
    count = 0
    i = 0
    while i <= len(tokens) - n:
        if tokens[i : i + n] == needle:
            count += 1
            i += n
        else:
            i += 1
    return count


def scan_archive(
    archive_dir: Path,
    plan: ScanPlan,
    language: str = "en",
    engine: str = "stem",
) -> list[tuple[str | None, int]]:
    """(bucket, count) rows for ``plan`` over the archive; [] when nothing hits."""
    if not archive_dir.is_dir():
        return []
    analyzer = get_analyzer(language, engine)
    needle = analyzer.analyze(plan.term)
    if not needle:
        return []

    counts: Counter[str | None] = Counter()
    for folder in sorted(archive_dir.iterdir()):
        if not folder.is_dir():
            continue
        m = _DAY_DIR.match(folder.name)
        if not m:
            continue
        day, tool = m.group(1), m.group(2) or "unknown"
        day_iso = f"{day}T00:00:00"
        if plan.since and day_iso < plan.since:
            continue
        if plan.until and day_iso >= plan.until:
            continue
        try:
            key = _bucket(day, tool, plan.group_by)
        except ValueError:  # malformed date in a hand-made folder name
            continue
        for f in sorted(folder.glob("*.jsonl")):
            _, turns = load_session(f, text_trunc=0)
            for t in turns:
                if t.kind != "text" or not t.text:
                    continue
                n = _count_occurrences(analyzer.analyze(t.text), needle)
                if n:
                    counts[key] += n

    rows = [(k, v) for k, v in counts.items() if v > 0]
    reverse = plan.order != "asc"
    rows.sort(key=lambda r: (r[1], str(r[0] or "")), reverse=reverse)
    if plan.limit is not None:
        rows = rows[: max(0, plan.limit)]
    return rows
