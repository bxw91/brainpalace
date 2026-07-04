"""Phase 2 — scan router eval (router-growth rule).

Boundary and negative cases against ALL existing modes, plus the
compute<->scan tie-break: a typed record metric that resolves -> compute
wins; else scan. Deterministic, key-free, no server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainpalace_server.models.record import Record
from brainpalace_server.services.compute_compiler import compile_compute
from brainpalace_server.services.query_router import (
    classify_compute_intent,
    classify_scan_intent,
)
from brainpalace_server.services.scan_compiler import compile_scan
from brainpalace_server.services.scan_executor import scan_archive
from brainpalace_server.storage.record_store import RecordStore

# (query, expect_scan_intent) — negatives cover retrieval- and compute-shaped
# queries; positives are utterance-history questions.
ROUTING_CASES = [
    ("which week did I mention foobar most", True),
    ("how many times did I say refactor", True),
    ("how often did I talk about caching per month", True),
    ("how do I configure authentication", False),  # hybrid/vector
    ("Retry-After header 429 Too Many Requests", False),  # bm25
    ("what depends on graph_store.py", False),  # graph
    ("how many files did I touch per week", False),  # compute
    ("total sales per month", False),  # compute
]


@pytest.mark.parametrize("q,expected", ROUTING_CASES)
def test_scan_intent_boundaries(q: str, expected: bool) -> None:
    assert classify_scan_intent(q) is expected, q


def test_tiebreak_typed_metric_wins(tmp_path: Path) -> None:
    """'how many X did I <verb>' with a REAL metric compiles for compute —
    compute runs first in the auto-router, so it wins. The same shape with no
    metric compiles to None for compute and to a plan for scan."""
    rs = RecordStore(tmp_path / "r.db")
    rs.insert_records(
        [
            Record(
                id="a",
                subject="session",
                metric="files_touched",
                value=3.0,
                ts="2026-01-12T00:00:00",
                confidence=1.0,
            )
        ]
    )
    metrics = rs.distinct_metrics()

    compute_q = "how many files did I touch per week"
    assert classify_compute_intent(compute_q)
    assert compile_compute(compute_q, metrics) is not None  # compute wins

    scan_q = "how many times did I mention foobar"
    assert classify_compute_intent(scan_q)  # 'how many' trips compute too …
    assert compile_compute(scan_q, metrics) is None  # … but no metric resolves
    assert classify_scan_intent(scan_q)
    plan = compile_scan(scan_q)
    assert plan is not None and plan.term == "foobar"  # scan takes it


def _line(text: str, ts: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "sessionId": "s",
            "timestamp": ts,
            "message": {"role": "user", "content": text},
        }
    )


def test_exit_criterion_which_week_most(tmp_path: Path) -> None:
    """Roadmap exit: 'which week did I say word X most' answered
    deterministically."""
    root = tmp_path / "session_archive"
    (root / "2026-01-05-claude-code").mkdir(parents=True)
    (root / "2026-01-12-claude-code").mkdir(parents=True)
    (root / "2026-01-05-claude-code" / "a.jsonl").write_text(
        _line("deploy went fine", "2026-01-05T09:00:00Z") + "\n", encoding="utf-8"
    )
    (root / "2026-01-12-claude-code" / "b.jsonl").write_text(
        _line("deploy deploy deploy", "2026-01-12T09:00:00Z") + "\n",
        encoding="utf-8",
    )
    plan = compile_scan("which week did I say the word deploy most")
    assert plan is not None
    rows = scan_archive(root, plan)
    assert rows == [("2026-W03", 3)]
