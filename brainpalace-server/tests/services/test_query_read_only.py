"""Read-only query: vector/hybrid/multi run BM25 instead of calling embed_query."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models import QueryMode, QueryRequest
from brainpalace_server.services import query_service as qs


async def _identity_memory_boost(request, response):
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [QueryMode.VECTOR, QueryMode.HYBRID, QueryMode.MULTI])
async def test_read_only_falls_back_to_bm25(monkeypatch, mode):
    monkeypatch.setattr(qs, "is_read_only", lambda: True)
    monkeypatch.setattr(qs, "_decay_half_life", lambda: 0)

    service = qs.QueryService.__new__(qs.QueryService)  # bypass heavy __init__
    service.is_ready = lambda: True
    service.query_cache = None
    service.embedding_generator = MagicMock()  # embed_query must never be awaited

    # storage_backend.get_count() is checked before the dispatch block to guard
    # against empty-index early return; return 1 so execution reaches the gate.
    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=1)
    service.storage_backend = storage_backend
    service._execute_bm25_query = AsyncMock(return_value=[])
    service._execute_vector_query = AsyncMock(return_value=[])
    service._execute_hybrid_query = AsyncMock(return_value=[])
    service._execute_multi_query = AsyncMock(return_value=[])
    service._execute_graph_query = AsyncMock(return_value=[])
    service._apply_stale_decision_penalty = lambda r: r
    service._apply_memory_boost = _identity_memory_boost

    request = QueryRequest(query="hello", mode=mode, top_k=5)
    await service.execute_query(request)

    service._execute_bm25_query.assert_awaited()
    service._execute_vector_query.assert_not_awaited()
    service._execute_hybrid_query.assert_not_awaited()
    service._execute_multi_query.assert_not_awaited()
    service.embedding_generator.embed_query.assert_not_called()
