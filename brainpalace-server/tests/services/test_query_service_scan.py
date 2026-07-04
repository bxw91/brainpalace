"""Phase 2 Task 6 — scan execution + tie-break wiring in QueryService."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.services.query_service import QueryService


def _archive(tmp_path: Path) -> Path:
    root = tmp_path / "session_archive"
    d = root / "2026-01-12-claude-code"
    d.mkdir(parents=True)
    line = json.dumps(
        {
            "type": "user",
            "sessionId": "s",
            "timestamp": "2026-01-12T09:00:00Z",
            "message": {"role": "user", "content": "foobar and foobar again"},
        }
    )
    (d / "a.jsonl").write_text(line + "\n", encoding="utf-8")
    return root


def _svc(archive_dir: Path | None) -> QueryService:
    return QueryService(storage_backend=None, archive_dir=archive_dir)


@pytest.mark.asyncio
async def test_scan_rows_from_archive(tmp_path: Path) -> None:
    svc = _svc(_archive(tmp_path))
    rows = await svc._execute_scan_query(
        QueryRequest(query="which week did I mention foobar most", mode=QueryMode.SCAN)
    )
    assert len(rows) == 1
    assert rows[0].label == "2026-W03"
    assert rows[0].value == 2.0
    assert rows[0].term == "foobar"
    assert rows[0].score == 1.0


@pytest.mark.asyncio
async def test_no_archive_dir_returns_empty(tmp_path: Path) -> None:
    svc = _svc(None)
    rows = await svc._execute_scan_query(
        QueryRequest(query="which week did I mention foobar most", mode=QueryMode.SCAN)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_no_term_returns_empty(tmp_path: Path) -> None:
    svc = _svc(_archive(tmp_path))
    rows = await svc._execute_scan_query(
        QueryRequest(query="what is the indexer architecture", mode=QueryMode.SCAN)
    )
    assert rows == []


def _full_flow_svc(archive_dir: Path | None) -> QueryService:
    """A QueryService that clears execute_query's pre-dispatch gates.

    Bypasses the heavy __init__ (mirrors tests/services/test_query_read_only.py)
    so the full execute_query() flow can be exercised: is_ready() must report
    True and storage_backend.get_count() must be non-zero to reach the
    scan/compute early-return blocks at all.
    """
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    svc.record_store = None
    svc.archive_dir = archive_dir
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    return svc


@pytest.mark.asyncio
async def test_mode_scan_early_return(tmp_path: Path) -> None:
    svc = _full_flow_svc(_archive(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(query="how many times did I say foobar", mode=QueryMode.SCAN)
    )
    assert resp.results == []
    assert resp.scan is not None and resp.scan[0].value == 2.0
    assert resp.total_results == 1


@pytest.mark.asyncio
async def test_hybrid_auto_routes_to_scan(tmp_path: Path) -> None:
    # No record_store attached -> compute cannot win the tie-break; scan rows
    # come back on a plain HYBRID request carrying scan tells.
    svc = _full_flow_svc(_archive(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(query="how many times did I say foobar", mode=QueryMode.HYBRID)
    )
    assert resp.scan is not None and resp.scan[0].value == 2.0
    assert resp.results == []
