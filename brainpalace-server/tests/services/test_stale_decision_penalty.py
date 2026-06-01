"""Stale-decision ranking penalty (Phase 140)."""

from __future__ import annotations

import pytest

from brainpalace_server.config import settings
from brainpalace_server.models.query import QueryResult
from brainpalace_server.services.query_service import QueryService


class FakeGraphStore:
    """timeline() reports the superseded-by edges for a decision name."""

    def __init__(self, stale_names: set[str]) -> None:
        self.stale = stale_names

    def timeline(self, entity_name: str):
        if entity_name in self.stale:
            return [
                {
                    "subject": entity_name,
                    "predicate": "superseded-by",
                    "object": "newer",
                    "valid": True,
                }
            ]
        return []


class FakeGraphMgr:
    def __init__(self, stale_names: set[str]) -> None:
        self.graph_store = FakeGraphStore(stale_names)


def _svc(stale_names: set[str]) -> QueryService:
    svc = object.__new__(QueryService)  # type: ignore[call-arg]
    svc.graph_index_manager = FakeGraphMgr(stale_names)
    return svc


def _decision(text: str, score: float) -> QueryResult:
    return QueryResult(
        text=text,
        source="s",
        score=score,
        chunk_id=text,
        source_type="session_decision",
    )


def test_stale_decision_is_penalised_and_reordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    results = [
        _decision("use in-memory cache", 1.0),  # stale
        _decision("use Redis cache", 0.9),  # current
    ]
    out = _svc({"use in-memory cache"})._apply_stale_decision_penalty(results)
    assert out[0].chunk_id == "use Redis cache"  # current now ranks first
    assert out[1].score == pytest.approx(0.5)  # stale halved


def test_penalty_one_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 1.0)
    results = [_decision("use in-memory cache", 1.0)]
    out = _svc({"use in-memory cache"})._apply_stale_decision_penalty(results)
    assert out[0].score == 1.0


def test_non_decision_results_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    r = QueryResult(
        text="use in-memory cache",
        source="s",
        score=1.0,
        chunk_id="c",
        source_type="code",
    )
    out = _svc({"use in-memory cache"})._apply_stale_decision_penalty([r])
    assert out[0].score == 1.0


def test_no_graph_manager_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    svc = object.__new__(QueryService)  # type: ignore[call-arg]
    svc.graph_index_manager = None
    r = _decision("x", 1.0)
    assert svc._apply_stale_decision_penalty([r])[0].score == 1.0


def test_current_decision_not_penalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    r = _decision("fresh decision", 1.0)
    out = _svc(set())._apply_stale_decision_penalty([r])
    assert out[0].score == 1.0
