"""Task 6 — QueryService: `_sensitivity_allowed` resolver + per-data-path
default-deny wiring (compute, absence, timeline, graph, chunk tail, scan,
query cache boundary).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest, QueryResult
from brainpalace_server.models.record import Record
from brainpalace_server.services.query_cache import QueryCacheService
from brainpalace_server.services.query_service import (
    QueryService,
    _sensitivity_allowed,
)
from brainpalace_server.storage.record_store import RecordStore


def test_resolver_default_deny():
    assert _sensitivity_allowed(QueryRequest(query="x")) is False


def test_resolver_opt_in():
    assert _sensitivity_allowed(QueryRequest(query="x", include_sensitive=True)) is True


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


def _rec(rid, value, sensitivity="normal"):
    return Record(
        id=rid,
        subject="proj",
        metric="cost",
        value=value,
        source="s",
        confidence=1.0,
        sensitivity=sensitivity,
    )


@pytest.mark.asyncio
async def test_compute_excludes_sensitive_row(tmp_path):
    rs = RecordStore(str(tmp_path / "r.db"))
    rs.insert_records([_rec("a", 10.0), _rec("b", 5.0, sensitivity="private")])
    svc = QueryService.__new__(QueryService)
    svc.record_store = rs

    hidden = await svc._execute_compute_query(
        QueryRequest(query="what is the total cost", mode=QueryMode.COMPUTE)
    )
    assert sum(r.value for r in hidden) == 10.0

    revealed = await svc._execute_compute_query(
        QueryRequest(
            query="what is the total cost",
            mode=QueryMode.COMPUTE,
            include_sensitive=True,
        )
    )
    assert sum(r.value for r in revealed) == 15.0


# ---------------------------------------------------------------------------
# Absence
# ---------------------------------------------------------------------------


def _absence_rec(rid, subject, metric, sensitivity="normal"):
    return Record(
        id=rid,
        subject=subject,
        metric=metric,
        value=1.0,
        domain="chat-life",
        source="s",
        confidence=1.0,
        sensitivity=sensitivity,
    )


@pytest.mark.asyncio
async def test_absence_excludes_sensitive_row(tmp_path):
    rs = RecordStore(str(tmp_path / "r.db"))
    rs.insert_records(
        [
            _absence_rec("a", "run", "distance"),
            _absence_rec("b", "walk", "distance"),
            # "walk" only has "duration" via a private row -> reads as absent
            # by default (privacy-consistent anti-join semantics), present
            # once revealed.
            _absence_rec("c", "walk", "duration", sensitivity="private"),
        ]
    )
    svc = QueryService.__new__(QueryService)
    svc.record_store = rs

    # By default, "walk"'s only duration row is invisible (private), so it
    # reads as absent too -- both subjects come back (privacy-consistent
    # anti-join semantics, per record_store.absent_subjects's documented
    # intentional behavior: sensitive = invisible = absent).
    hidden = await svc._execute_absence_query(
        QueryRequest(
            query="subjects with distance but not duration", mode=QueryMode.ABSENCE
        )
    )
    assert {r.label for r in hidden} == {"run", "walk"}

    # Revealed: "walk"'s private duration row becomes visible, so "walk" is no
    # longer absent -- only "run" (genuinely absent) remains.
    revealed = await svc._execute_absence_query(
        QueryRequest(
            query="subjects with distance but not duration",
            mode=QueryMode.ABSENCE,
            include_sensitive=True,
        )
    )
    assert [r.label for r in revealed] == ["run"]


# ---------------------------------------------------------------------------
# Timeline (flag threading into the graph wrapper)
# ---------------------------------------------------------------------------


class _CapturingGraph:
    """Records the include_sensitive flag each call was made with."""

    def __init__(self) -> None:
        self.search_calls: list[bool] = []
        self.timeline_calls: list[bool] = []

    def search_nodes(self, text, limit=20, domains=None, include_sensitive=False):
        self.search_calls.append(include_sensitive)
        return [{"id": "n", "name": "the cache", "label": "Decision", "degree": 1}]

    def timeline_named(self, entity_name, include_sensitive=False):
        self.timeline_calls.append(include_sensitive)
        return [
            {
                "subject": "the cache",
                "predicate": "touches",
                "object": "cache.py",
                "valid_from": "2026-01-01T00:00:00",
                "valid_until": None,
            }
        ]


@pytest.mark.asyncio
async def test_timeline_threads_include_sensitive_flag():
    from types import SimpleNamespace

    graph = _CapturingGraph()
    svc = QueryService(storage_backend=None)
    svc.graph_index_manager = SimpleNamespace(graph_store=graph)

    await svc._execute_timeline_query(
        QueryRequest(query="history of the cache", mode=QueryMode.TIMELINE)
    )
    await svc._execute_timeline_query(
        QueryRequest(
            query="history of the cache",
            mode=QueryMode.TIMELINE,
            include_sensitive=True,
        )
    )

    assert graph.search_calls == [False, True]
    assert graph.timeline_calls == [False, True]


# ---------------------------------------------------------------------------
# Graph (both query() and query_by_type() branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_query_threads_include_sensitive(monkeypatch):
    from brainpalace_server.config import settings

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    monkeypatch.setattr(
        "brainpalace_server.storage.get_effective_backend_type", lambda: "chroma"
    )

    svc = QueryService.__new__(QueryService)
    svc.graph_index_manager = MagicMock()
    svc.graph_index_manager.query = MagicMock(return_value=[])
    svc._execute_vector_query = AsyncMock(return_value=[])

    await svc._execute_graph_query(
        QueryRequest(query="who calls foo", mode=QueryMode.GRAPH)
    )
    await svc._execute_graph_query(
        QueryRequest(
            query="who calls foo", mode=QueryMode.GRAPH, include_sensitive=True
        )
    )

    calls = svc.graph_index_manager.query.call_args_list
    assert calls[0].kwargs["include_sensitive"] is False
    assert calls[1].kwargs["include_sensitive"] is True


@pytest.mark.asyncio
async def test_graph_query_by_type_threads_include_sensitive(monkeypatch):
    from brainpalace_server.config import settings

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    monkeypatch.setattr(
        "brainpalace_server.storage.get_effective_backend_type", lambda: "chroma"
    )

    svc = QueryService.__new__(QueryService)
    svc.graph_index_manager = MagicMock()
    svc.graph_index_manager.query_by_type = MagicMock(return_value=[])
    svc._execute_vector_query = AsyncMock(return_value=[])

    request = QueryRequest(
        query="who calls foo", mode=QueryMode.GRAPH, entity_types=["Function"]
    )
    await svc._execute_graph_query(request)
    await svc._execute_graph_query(
        request.model_copy(update={"include_sensitive": True})
    )

    calls = svc.graph_index_manager.query_by_type.call_args_list
    assert calls[0].kwargs["include_sensitive"] is False
    assert calls[1].kwargs["include_sensitive"] is True


# ---------------------------------------------------------------------------
# Chunk tail post-filter + cache boundary
# ---------------------------------------------------------------------------


async def _identity_memory_boost(request, response):
    return response


def _full_flow_svc(bm25_results):
    svc = QueryService.__new__(QueryService)
    svc.is_ready = lambda: True
    svc.query_cache = None
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    svc.storage_backend = storage_backend
    svc._execute_bm25_query = AsyncMock(return_value=bm25_results)
    svc._apply_memory_boost = _identity_memory_boost
    return svc


_NORMAL_RESULT = QueryResult(
    text="public turn",
    source="s",
    score=1.0,
    chunk_id="c1",
    source_type="doc",
    metadata={"sensitivity": "normal"},
)
_PRIVATE_RESULT = QueryResult(
    text="secret turn",
    source="s",
    score=1.0,
    chunk_id="c2",
    source_type="doc",
    metadata={"sensitivity": "private"},
)


@pytest.mark.asyncio
async def test_chunk_tail_hides_sensitive_by_default():
    svc = _full_flow_svc([_NORMAL_RESULT, _PRIVATE_RESULT])
    resp = await svc.execute_query(QueryRequest(query="x", mode=QueryMode.BM25))
    assert [r.chunk_id for r in resp.results] == ["c1"]


@pytest.mark.asyncio
async def test_chunk_tail_reveals_with_flag():
    svc = _full_flow_svc([_NORMAL_RESULT, _PRIVATE_RESULT])
    resp = await svc.execute_query(
        QueryRequest(query="x", mode=QueryMode.BM25, include_sensitive=True)
    )
    assert {r.chunk_id for r in resp.results} == {"c1", "c2"}


@pytest.mark.asyncio
async def test_cache_boundary_does_not_leak_sensitive_across_flag():
    """Regression: a revealed response must not poison the cache slot a
    later default (e.g. MCP) call reads from."""
    svc = _full_flow_svc([_NORMAL_RESULT, _PRIVATE_RESULT])
    svc.query_cache = QueryCacheService()

    revealed_resp = await svc.execute_query(
        QueryRequest(query="x", mode=QueryMode.BM25, include_sensitive=True)
    )
    assert {r.chunk_id for r in revealed_resp.results} == {"c1", "c2"}

    default_resp = await svc.execute_query(QueryRequest(query="x", mode=QueryMode.BM25))
    assert [r.chunk_id for r in default_resp.results] == ["c1"]


# ---------------------------------------------------------------------------
# Scan (archive) wiring
# ---------------------------------------------------------------------------


def _write_session(day_folder, session_id, term):
    import json

    day_folder.mkdir(parents=True, exist_ok=True)
    f = day_folder / f"{session_id}.jsonl"
    lines = [
        {
            "type": "user",
            "sessionId": session_id,
            "message": {"role": "user", "content": f"{term} {term}"},
        },
    ]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_scan_query_wires_private_session_ids(tmp_path, monkeypatch):
    archive = tmp_path / "session_archive"
    day = archive / "2026-05-20-claude-code"
    _write_session(day, "pub-session", "widget")
    _write_session(day, "sec-session", "widget")

    svc = QueryService(storage_backend=None, archive_dir=archive)
    monkeypatch.setattr(svc, "_private_session_ids", lambda: {"sec-session"})

    hidden = await svc._execute_scan_query(
        QueryRequest(query="which week did I mention widget most", mode=QueryMode.SCAN)
    )
    assert sum(r.value for r in hidden) == 2.0  # only pub-session counted

    revealed = await svc._execute_scan_query(
        QueryRequest(
            query="which week did I mention widget most",
            mode=QueryMode.SCAN,
            include_sensitive=True,
        )
    )
    assert sum(r.value for r in revealed) == 4.0  # both sessions counted
