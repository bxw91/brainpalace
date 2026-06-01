"""E2E validation: time-decay (110) + stale-decision penalty (140) compose.

Mirrors the order in QueryService.execute_query: _apply_time_decay then
_apply_stale_decision_penalty. Keyless (real ranking methods, no embeddings).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from brainpalace_server.config import settings
from brainpalace_server.models.query import QueryRequest, QueryResult
from brainpalace_server.services.query_service import QueryService


class _StaleGraph:
    def timeline(self, name: str):
        if name == "old decision":
            return [
                {
                    "subject": "old decision",
                    "predicate": "superseded-by",
                    "object": "new",
                    "valid": True,
                }
            ]
        return []


def _svc() -> QueryService:
    svc = object.__new__(QueryService)  # type: ignore[call-arg]
    svc.graph_index_manager = type("GM", (), {"graph_store": _StaleGraph()})()
    return svc


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _r(cid, score, created_days, decision=False, text=None) -> QueryResult:
    return QueryResult(
        text=text or cid,
        source=cid,
        score=score,
        chunk_id=cid,
        source_type="session_decision" if decision else "doc",
        metadata={"created_at": _iso(created_days)},
    )


def test_decay_then_penalty_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 30.0)
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    svc = _svc()
    req = QueryRequest(query="q", time_decay=True)

    results = [
        _r("old_doc", 1.0, 365),  # decays heavily
        _r("new_doc", 1.0, 1),  # barely decays → should win
        _r("old decision", 1.0, 1, decision=True, text="old decision"),  # stale
    ]
    results = svc._apply_time_decay(results, req)
    results = svc._apply_stale_decision_penalty(results)

    # newest non-stale doc ranks first; the stale recent decision is pushed down
    assert results[0].chunk_id == "new_doc"
    scores = {r.chunk_id: r.score for r in results}
    assert scores["old_doc"] < scores["new_doc"]  # decay
    assert scores["old decision"] < scores["new_doc"]  # decay≈none + penalty
    assert scores["old decision"] == pytest.approx(0.5, abs=0.05)  # ~1.0*decay*0.5
