"""Time-decay ranking (Phase 110)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from brainpalace_server.config import settings
from brainpalace_server.models.query import QueryRequest, QueryResult
from brainpalace_server.services.query_service import QueryService


def _svc() -> QueryService:
    # bypass __init__ — _apply_time_decay only needs settings + request
    return object.__new__(QueryService)  # type: ignore[call-arg]


def _result(chunk_id: str, score: float, created_at: str | None) -> QueryResult:
    meta = {}
    if created_at is not None:
        meta["created_at"] = created_at
    return QueryResult(
        text="t",
        source="s",
        score=score,
        chunk_id=chunk_id,
        source_type="doc",
        metadata=meta,
    )


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _req(time_decay: bool = True) -> QueryRequest:
    return QueryRequest(query="q", time_decay=time_decay)


def test_newer_outranks_older_at_equal_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 90.0)
    results = [
        _result("old", 1.0, _iso(365)),
        _result("new", 1.0, _iso(1)),
    ]
    out = _svc()._apply_time_decay(results, _req())
    assert out[0].chunk_id == "new"
    assert out[1].chunk_id == "old"


def test_half_life_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 30.0)
    r = _result("x", 1.0, _iso(30))  # one half-life old
    _svc()._apply_time_decay([r], _req())
    assert r.score == pytest.approx(0.5, abs=0.02)


def test_half_life_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 0.0)
    results = [_result("old", 0.9, _iso(365)), _result("new", 0.8, _iso(1))]
    out = _svc()._apply_time_decay(results, _req())
    assert [r.chunk_id for r in out] == ["old", "new"]  # untouched order
    assert out[0].score == 0.9


def test_request_flag_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 90.0)
    r = _result("x", 1.0, _iso(365))
    _svc()._apply_time_decay([r], _req(time_decay=False))
    assert r.score == 1.0


def test_missing_created_at_no_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 90.0)
    r = _result("x", 1.0, None)
    _svc()._apply_time_decay([r], _req())
    assert r.score == 1.0


def test_naive_created_at_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 30.0)
    aware = datetime.now(timezone.utc) - timedelta(days=30)
    naive = aware.replace(tzinfo=None).isoformat()  # no tzinfo
    r = _result("x", 1.0, naive)
    _svc()._apply_time_decay([r], _req())
    assert r.score == pytest.approx(0.5, abs=0.05)
