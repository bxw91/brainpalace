"""Per-request rerank override (Retrieval Explorer, dashboard plan 01).

``QueryRequest.rerank`` overrides the global ``ENABLE_RERANKING`` gate:
True forces the two-stage reranker, False disables it, None (default)
follows the setting.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainpalace_server.models import QueryMode, QueryRequest, QueryResult
from brainpalace_server.services.query_service import QueryService


@pytest.fixture
def query_service():
    mock_vector_store = MagicMock()
    mock_vector_store.is_initialized = True
    mock_vector_store.get_count = AsyncMock(return_value=100)
    mock_embedding_gen = MagicMock()
    mock_embedding_gen.embed_query = AsyncMock(return_value=[0.1] * 768)
    mock_bm25 = MagicMock()
    mock_bm25.is_initialized = True
    return QueryService(
        vector_store=mock_vector_store,
        embedding_generator=mock_embedding_gen,
        bm25_manager=mock_bm25,
        graph_index_manager=MagicMock(),
    )


def _sample_results(n: int = 10) -> list[QueryResult]:
    return [
        QueryResult(
            text=f"Document {i}",
            source=f"doc{i}.txt",
            score=1.0 - i * 0.05,
            chunk_id=f"chunk_{i}",
        )
        for i in range(n)
    ]


def _settings(enabled: bool) -> MagicMock:
    s = MagicMock()
    s.ENABLE_RERANKING = enabled
    s.RERANKER_TOP_K_MULTIPLIER = 10
    s.RERANKER_MAX_CANDIDATES = 100
    return s


def test_rerank_field_defaults_to_none():
    req = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5)
    assert req.rerank is None


@pytest.mark.asyncio
async def test_rerank_false_disables_despite_global_on(query_service):
    with (
        patch.object(
            query_service,
            "_execute_hybrid_query",
            new_callable=AsyncMock,
            return_value=_sample_results(),
        ),
        patch.object(
            query_service, "_rerank_results", new_callable=AsyncMock
        ) as mock_rerank,
        patch("brainpalace_server.services.query_service.settings", _settings(True)),
    ):
        req = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5, rerank=False)
        await query_service.execute_query(req)
        mock_rerank.assert_not_called()


@pytest.mark.asyncio
async def test_rerank_true_forces_despite_global_off(query_service):
    with (
        patch.object(
            query_service,
            "_execute_hybrid_query",
            new_callable=AsyncMock,
            return_value=_sample_results(),
        ),
        patch.object(
            query_service,
            "_rerank_results",
            new_callable=AsyncMock,
            return_value=_sample_results(5),
        ) as mock_rerank,
        patch("brainpalace_server.services.query_service.settings", _settings(False)),
    ):
        req = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5, rerank=True)
        await query_service.execute_query(req)
        mock_rerank.assert_called_once()


@pytest.mark.asyncio
async def test_rerank_none_follows_global_setting(query_service):
    with (
        patch.object(
            query_service,
            "_execute_hybrid_query",
            new_callable=AsyncMock,
            return_value=_sample_results(),
        ),
        patch.object(
            query_service,
            "_rerank_results",
            new_callable=AsyncMock,
            return_value=_sample_results(5),
        ) as mock_rerank,
        patch("brainpalace_server.services.query_service.settings", _settings(True)),
    ):
        req = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5)
        await query_service.execute_query(req)
        mock_rerank.assert_called_once()


@pytest.mark.asyncio
async def test_rerank_true_and_false_do_not_share_cache_entry():
    """rerank=True and rerank=False must produce distinct cache keys.

    Uses a real QueryCacheService: the first (rerank=True) response is
    cached; an otherwise-identical rerank=False request must MISS that
    entry (fresh retrieval), while a repeated rerank=False request HITS
    its own entry.
    """
    from brainpalace_server.services.query_cache import QueryCacheService

    mock_vector_store = MagicMock()
    mock_vector_store.is_initialized = True
    mock_vector_store.get_count = AsyncMock(return_value=100)
    mock_embedding_gen = MagicMock()
    mock_embedding_gen.embed_query = AsyncMock(return_value=[0.1] * 768)
    mock_bm25 = MagicMock()
    mock_bm25.is_initialized = True
    service = QueryService(
        vector_store=mock_vector_store,
        embedding_generator=mock_embedding_gen,
        bm25_manager=mock_bm25,
        graph_index_manager=MagicMock(),
        query_cache=QueryCacheService(ttl=60, max_size=10),
    )

    with (
        patch.object(
            service,
            "_execute_hybrid_query",
            new_callable=AsyncMock,
            return_value=_sample_results(),
        ) as mock_hybrid,
        patch.object(
            service,
            "_rerank_results",
            new_callable=AsyncMock,
            return_value=_sample_results(5),
        ) as mock_rerank,
        patch("brainpalace_server.services.query_service.settings", _settings(False)),
    ):
        req_on = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5, rerank=True)
        req_off = QueryRequest(query="q", mode=QueryMode.HYBRID, top_k=5, rerank=False)

        await service.execute_query(req_on)
        assert mock_hybrid.call_count == 1
        mock_rerank.assert_called_once()

        # Different rerank value -> cache MISS -> retrieval runs again,
        # and reranking is NOT applied this time.
        await service.execute_query(req_off)
        assert mock_hybrid.call_count == 2
        mock_rerank.assert_called_once()

        # Same rerank value as previous call -> cache HIT -> no new retrieval.
        await service.execute_query(req_off)
        assert mock_hybrid.call_count == 2
