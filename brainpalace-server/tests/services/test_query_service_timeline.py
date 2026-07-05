"""Phase 4 Task 5 — timeline execution + auto-route wiring in QueryService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.services.query_service import QueryService


class _FakeGraph:
    """Minimal graph facade surface timeline mode uses."""

    def __init__(self) -> None:
        self._rows = {
            "use in-memory cache": [
                {
                    "subject": "use in-memory cache",
                    "predicate": "touches",
                    "object": "cache.py",
                    "valid_from": "2026-01-01T00:00:00",
                    "valid_until": "2026-03-01T00:00:00",
                    "valid": False,
                },
                {
                    "subject": "use in-memory cache",
                    "predicate": "superseded-by",
                    "object": "use Redis cache",
                    "valid_from": "2026-03-01T00:00:00",
                    "valid_until": None,
                    "valid": True,
                },
            ]
        }

    def search_nodes(self, text: str, limit: int = 20, domains=None):
        for name in self._rows:
            if text.lower() in name.lower():
                return [{"id": "n", "name": name, "label": "Decision", "degree": 2}]
        return []

    def timeline_named(self, entity_name: str):
        return self._rows.get(entity_name, [])


def _svc(graph: object | None) -> QueryService:
    svc = QueryService(storage_backend=None)
    svc.graph_index_manager = SimpleNamespace(graph_store=graph)
    return svc


def _full_flow_svc(graph: object | None) -> QueryService:
    """A QueryService that clears execute_query's pre-dispatch gates.

    Bypasses the heavy __init__ (mirrors tests/services/test_query_service_absence.py's
    ``_full_flow_svc``) so the full execute_query() flow can be exercised:
    is_ready() must report True and storage_backend.get_count() must be
    non-zero to reach the timeline early-return / auto-route blocks at all.
    """
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    svc.record_store = None
    svc.archive_dir = None
    svc.graph_index_manager = SimpleNamespace(graph_store=graph)
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    return svc


@pytest.mark.asyncio
async def test_timeline_rows() -> None:
    svc = _svc(_FakeGraph())
    rows = await svc._execute_timeline_query(
        QueryRequest(
            query="how did the in-memory cache evolve", mode=QueryMode.TIMELINE
        )
    )
    assert [r.predicate for r in rows] == ["touches", "superseded-by"]
    assert rows[0].valid is False and rows[0].object == "cache.py"
    assert rows[1].valid is True


@pytest.mark.asyncio
async def test_no_graph_returns_empty() -> None:
    rows = await _svc(None)._execute_timeline_query(
        QueryRequest(query="history of cache.py", mode=QueryMode.TIMELINE)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_no_plan_returns_empty() -> None:
    rows = await _svc(_FakeGraph())._execute_timeline_query(
        QueryRequest(query="what is the indexer architecture", mode=QueryMode.TIMELINE)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_unknown_entity_returns_empty() -> None:
    rows = await _svc(_FakeGraph())._execute_timeline_query(
        QueryRequest(query="history of nonexistent", mode=QueryMode.TIMELINE)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_exact_name_wins_over_busier_substring() -> None:
    """H2: an exact node-name match beats a busier substring hit."""

    class _G:
        def search_nodes(self, text, limit=20, domains=None):
            # busiest substring hit first, exact match second
            return [
                {"name": "oauth.py", "degree": 9},
                {"name": "auth.py", "degree": 1},
            ]

        def timeline_named(self, entity_name):
            return (
                [
                    {
                        "subject": "auth.py",
                        "predicate": "imports",
                        "object": "os",
                        "valid_from": "2026-01-01T00:00:00",
                        "valid_until": None,
                    }
                ]
                if entity_name == "auth.py"
                else []
            )

    rows = await _svc(_G())._execute_timeline_query(
        QueryRequest(query="history of auth.py", mode=QueryMode.TIMELINE)
    )
    assert rows and rows[0].subject == "auth.py"


@pytest.mark.asyncio
async def test_mode_timeline_early_return() -> None:
    svc = _full_flow_svc(_FakeGraph())
    resp = await svc.execute_query(
        QueryRequest(
            query="how did the in-memory cache evolve", mode=QueryMode.TIMELINE
        )
    )
    assert resp.results == []
    assert resp.timeline is not None and resp.timeline[0].predicate == "touches"
    assert resp.total_results == 2


@pytest.mark.asyncio
async def test_hybrid_auto_routes_to_timeline() -> None:
    svc = _full_flow_svc(_FakeGraph())
    resp = await svc.execute_query(
        QueryRequest(query="how did the in-memory cache evolve", mode=QueryMode.HYBRID)
    )
    assert resp.timeline is not None and resp.timeline[0].predicate == "touches"
    assert resp.results == []
