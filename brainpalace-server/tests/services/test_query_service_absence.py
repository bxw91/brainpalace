"""Phase 3 Task 5 — absence execution + auto-route wiring in QueryService."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.models.record import Record
from brainpalace_server.services.query_service import QueryService
from brainpalace_server.storage.record_store import RecordStore


def _rec(subject: str, metric: str) -> Record:
    rid = hashlib.sha1(f"{subject}|{metric}".encode()).hexdigest()[:16]
    return Record(
        id=rid,
        subject=subject,
        metric=metric,
        value=1.0,
        domain="chat-life",
        source="session",
        ts="2026-01-05T00:00:00",
        confidence=1.0,
    )


def _store(tmp_path: Path) -> RecordStore:
    s = RecordStore(tmp_path / "r.db")
    s.insert_records(
        [_rec("run", "distance"), _rec("run", "duration"), _rec("walk", "distance")]
    )
    return s


def _svc(store: RecordStore | None) -> QueryService:
    return QueryService(storage_backend=None, record_store=store)


@pytest.mark.asyncio
async def test_absence_rows(tmp_path: Path) -> None:
    svc = _svc(_store(tmp_path))
    rows = await svc._execute_absence_query(
        QueryRequest(
            query="subjects with distance but not duration", mode=QueryMode.ABSENCE
        )
    )
    assert [r.label for r in rows] == ["walk"]
    assert rows[0].present_in == "distance"
    assert rows[0].absent_from == "duration"
    assert rows[0].partition == "metric"


@pytest.mark.asyncio
async def test_no_record_store_returns_empty() -> None:
    svc = _svc(None)
    rows = await svc._execute_absence_query(
        QueryRequest(query="a but not b", mode=QueryMode.ABSENCE)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_no_plan_returns_empty(tmp_path: Path) -> None:
    svc = _svc(_store(tmp_path))
    rows = await svc._execute_absence_query(
        QueryRequest(query="what is the indexer architecture", mode=QueryMode.ABSENCE)
    )
    assert rows == []


def _full_flow_svc(store: RecordStore | None) -> QueryService:
    """A QueryService that clears execute_query's pre-dispatch gates.

    Bypasses the heavy __init__ (mirrors tests/services/test_query_service_scan.py's
    ``_full_flow_svc``) so the full execute_query() flow can be exercised:
    is_ready() must report True and storage_backend.get_count() must be
    non-zero to reach the absence early-return / auto-route blocks at all.
    """
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    svc.record_store = store
    svc.archive_dir = None
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    return svc


@pytest.mark.asyncio
async def test_mode_absence_early_return(tmp_path: Path) -> None:
    svc = _full_flow_svc(_store(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(
            query="subjects with distance but not duration", mode=QueryMode.ABSENCE
        )
    )
    assert resp.results == []
    assert resp.absence is not None and resp.absence[0].label == "walk"
    assert resp.total_results == 1


@pytest.mark.asyncio
async def test_hybrid_auto_routes_to_absence(tmp_path: Path) -> None:
    svc = _full_flow_svc(_store(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(
            query="subjects with distance but not duration", mode=QueryMode.HYBRID
        )
    )
    assert resp.absence is not None and resp.absence[0].label == "walk"
    assert resp.results == []
