"""`routed_mode` — the response field that makes a silent re-route visible.

The contract under test: `routed_mode` is set when the EXECUTED mode differs
from the REQUESTED one, and null otherwise. The graph leg is the important
case — it returns plain `results`, indistinguishable in shape from hybrid, so
without this field a caller cannot tell its query changed mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest, QueryResult
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


def _svc(archive_dir: Path | None = None) -> QueryService:
    """execute_query's pre-dispatch gates cleared (mirrors the scan tests)."""
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    svc.record_store = None
    svc.archive_dir = archive_dir
    # The four early-return legs never reach these; the graph leg and the
    # read-only degrade both fall through the retrieval tail, which reads them
    # directly (not via getattr).
    svc.memory_service = None
    svc.reference_catalog_store = None
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    return svc


@pytest.mark.asyncio
async def test_explicit_mode_leaves_routed_mode_null(tmp_path: Path) -> None:
    """D5: requested == executed, so nothing was re-routed."""
    svc = _svc(_archive(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(query="how many times did I say foobar", mode=QueryMode.SCAN)
    )
    assert resp.scan is not None  # the query did run as scan
    assert resp.routed_mode is None


@pytest.mark.asyncio
async def test_hybrid_auto_routed_to_scan_reports_it(tmp_path: Path) -> None:
    svc = _svc(_archive(tmp_path))
    resp = await svc.execute_query(
        QueryRequest(query="how many times did I say foobar", mode=QueryMode.HYBRID)
    )
    assert resp.scan is not None
    assert resp.routed_mode == QueryMode.SCAN


@pytest.mark.asyncio
async def test_hybrid_auto_routed_to_graph_reports_it() -> None:
    """The case the field exists for.

    Graph returns plain `results` — same shape as hybrid — so this re-route is
    invisible without `routed_mode`. It is also the only leg that does NOT
    early-return: it falls through the whole retrieval tail (filters, decay,
    rerank, memory/reference boost), any step of which could drop the field.
    """
    svc = _svc()
    graph_store = MagicMock()
    svc.graph_index_manager = MagicMock(graph_store=graph_store)
    hit = QueryResult(
        text="def scan_archive(...)",
        source="services/scan_executor.py",
        score=0.9,
        chunk_id="c1",
        source_type="code",
    )
    svc._execute_graph_query = AsyncMock(return_value=[hit])

    resp = await svc.execute_query(
        QueryRequest(query="what calls scan_archive", mode=QueryMode.HYBRID)
    )

    assert resp.routed_mode == QueryMode.GRAPH
    assert [r.chunk_id for r in resp.results] == ["c1"]


@pytest.mark.asyncio
async def test_empty_graph_leg_does_not_claim_a_reroute() -> None:
    """An attempted-but-empty graph leg falls through to hybrid (finding #4).

    Nothing was re-routed, so claiming GRAPH here would be a lie — and would
    make the field fire on ordinary hybrid queries that merely LOOK
    relationship-shaped.
    """
    svc = _svc()
    svc.graph_index_manager = MagicMock(graph_store=MagicMock())
    svc._execute_graph_query = AsyncMock(return_value=[])
    svc._execute_hybrid_query = AsyncMock(return_value=[])

    resp = await svc.execute_query(
        QueryRequest(query="what calls scan_archive", mode=QueryMode.HYBRID)
    )
    assert resp.routed_mode is None


@pytest.mark.asyncio
async def test_read_only_degrade_to_bm25_reports_it(monkeypatch) -> None:
    """D3: read-only turns a hybrid query into a bm25 one — also a mode change."""
    monkeypatch.setattr(
        "brainpalace_server.services.query_service.is_read_only", lambda: True
    )
    svc = _svc()
    svc._execute_bm25_query = AsyncMock(return_value=[])

    resp = await svc.execute_query(
        QueryRequest(query="how does indexing work", mode=QueryMode.HYBRID)
    )
    assert resp.routed_mode == QueryMode.BM25
