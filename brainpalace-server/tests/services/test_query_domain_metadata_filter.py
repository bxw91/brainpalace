"""Round 4 D4 — query `domains`/`metadata_filter`: post-retrieval filtering,
cache-key separation, sensitivity composition, and over-fetch.

Uses the ``QueryService.__new__`` bypass-``__init__`` pattern established by
``tests/services/test_query_read_only.py`` — BM25 mode is forced so the
auto-router (compute/scan/absence/timeline) never engages, and
``_execute_bm25_query`` is mocked directly so these tests exercise the
post-retrieval filter/over-fetch/cache logic in isolation from real
retrieval.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest, QueryResult
from brainpalace_server.services import query_service as qs
from brainpalace_server.services.query_cache import QueryCacheService


def _result(
    chunk_id: str,
    *,
    domain: str | None = None,
    meta: dict[str, str] | None = None,
    sensitivity: str | None = None,
    score: float = 1.0,
) -> QueryResult:
    metadata = dict(meta or {})
    if domain is not None:
        metadata["domain"] = domain
    if sensitivity is not None:
        metadata["sensitivity"] = sensitivity
    return QueryResult(
        text=f"text-{chunk_id}",
        source=f"src/{chunk_id}.md",
        score=score,
        chunk_id=chunk_id,
        metadata=metadata,
    )


def _make_service(
    results: list[QueryResult], *, query_cache: QueryCacheService | None = None
) -> qs.QueryService:
    service = qs.QueryService.__new__(qs.QueryService)  # bypass heavy __init__
    service.is_ready = lambda: True
    service.query_cache = query_cache
    service.memory_service = None  # accessed directly (not getattr) — must exist
    service.embedding_generator = MagicMock()

    storage_backend = MagicMock()
    storage_backend.get_count = AsyncMock(return_value=max(len(results), 1))
    service.storage_backend = storage_backend

    service._execute_bm25_query = AsyncMock(return_value=list(results))
    service._execute_vector_query = AsyncMock(return_value=[])
    service._execute_hybrid_query = AsyncMock(return_value=[])
    service._execute_multi_query = AsyncMock(return_value=[])
    service._execute_graph_query = AsyncMock(return_value=[])
    return service


# ---------------------------------------------------------------------------
# Filter hits/misses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_filter_hits_and_misses() -> None:
    results = [
        _result("c1", domain="home-assistant"),
        _result("c2", domain="billing"),
    ]
    service = _make_service(results)
    request = QueryRequest(
        query="widgets", mode=QueryMode.BM25, top_k=5, domains=["home-assistant"]
    )
    response = await service.execute_query(request)
    assert [r.chunk_id for r in response.results] == ["c1"]


@pytest.mark.asyncio
async def test_metadata_filter_single_key() -> None:
    results = [
        _result("c1", meta={"owner": "alice"}),
        _result("c2", meta={"owner": "bob"}),
    ]
    service = _make_service(results)
    request = QueryRequest(
        query="widgets",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "alice"},
    )
    response = await service.execute_query(request)
    assert [r.chunk_id for r in response.results] == ["c1"]


@pytest.mark.asyncio
async def test_metadata_filter_two_keys_and() -> None:
    results = [
        _result("c1", meta={"owner": "alice", "kind": "log"}),
        _result("c2", meta={"owner": "alice", "kind": "note"}),  # kind mismatch
        _result("c3", meta={"owner": "bob", "kind": "log"}),  # owner mismatch
    ]
    service = _make_service(results)
    request = QueryRequest(
        query="widgets",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "alice", "kind": "log"},
    )
    response = await service.execute_query(request)
    assert [r.chunk_id for r in response.results] == ["c1"]


@pytest.mark.asyncio
async def test_metadata_filter_missing_key_excludes() -> None:
    """A chunk lacking the filtered key entirely must not match."""
    results = [
        _result("c1", meta={"owner": "alice"}),
        _result("c2", meta={}),  # no "owner" key at all
    ]
    service = _make_service(results)
    request = QueryRequest(
        query="widgets",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "alice"},
    )
    response = await service.execute_query(request)
    assert [r.chunk_id for r in response.results] == ["c1"]


# ---------------------------------------------------------------------------
# Compose with sensitivity default-deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_filter_composes_with_sensitivity_default_deny() -> None:
    results = [
        _result("c1", domain="home-assistant", sensitivity="sensitive"),
        _result("c2", domain="home-assistant", sensitivity="normal"),
    ]

    service = _make_service(results)
    request = QueryRequest(
        query="widgets", mode=QueryMode.BM25, top_k=5, domains=["home-assistant"]
    )
    response = await service.execute_query(request)
    assert [r.chunk_id for r in response.results] == ["c2"]

    service2 = _make_service(results)
    request2 = QueryRequest(
        query="widgets",
        mode=QueryMode.BM25,
        top_k=5,
        domains=["home-assistant"],
        include_sensitive=True,
    )
    response2 = await service2.execute_query(request2)
    assert {r.chunk_id for r in response2.results} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Over-fetch (D4 recall-loss mitigation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_fetch_when_domain_filter_set() -> None:
    results = [_result(f"c{i}") for i in range(3)]
    service = _make_service(results)
    request = QueryRequest(query="widgets", mode=QueryMode.BM25, top_k=5, domains=["x"])
    await service.execute_query(request)

    called_request = service._execute_bm25_query.call_args.args[0]
    assert called_request.top_k == 25  # top_k(5) * FILTER_TOP_K_MULTIPLIER(5)
    assert called_request.top_k != request.top_k


@pytest.mark.asyncio
async def test_over_fetch_when_metadata_filter_set() -> None:
    results = [_result(f"c{i}") for i in range(3)]
    service = _make_service(results)
    request = QueryRequest(
        query="widgets", mode=QueryMode.BM25, top_k=5, metadata_filter={"owner": "a"}
    )
    await service.execute_query(request)

    called_request = service._execute_bm25_query.call_args.args[0]
    assert called_request.top_k == 25


@pytest.mark.asyncio
async def test_no_over_fetch_without_domain_or_metadata_filter() -> None:
    results = [_result(f"c{i}") for i in range(3)]
    service = _make_service(results)
    request = QueryRequest(query="widgets", mode=QueryMode.BM25, top_k=5)
    await service.execute_query(request)

    called_request = service._execute_bm25_query.call_args.args[0]
    assert called_request.top_k == 5


@pytest.mark.asyncio
async def test_over_fetch_truncates_back_to_requested_top_k() -> None:
    """Over-fetched, filtered results are truncated back to the caller's
    top_k, not silently returned oversized."""
    results = [_result(f"c{i}", domain="d") for i in range(8)]
    service = _make_service(results)
    request = QueryRequest(query="widgets", mode=QueryMode.BM25, top_k=3, domains=["d"])
    response = await service.execute_query(request)
    assert len(response.results) == 3


# ---------------------------------------------------------------------------
# Cache-key separation — correctness, not hygiene (D4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_key_separates_by_metadata_filter_no_cross_contamination() -> None:
    """Same query text, different metadata_filter → distinct cache entries.

    Regression guard for the exact bug D4 calls out: if metadata_filter were
    omitted from cache_params, the second (owner=bob) query would incorrectly
    receive the first (owner=alice) query's cached, already-filtered results.
    """
    cache = QueryCacheService(ttl=60, max_size=10)

    results_a = [_result("c1", meta={"owner": "alice"})]
    service_a = _make_service(results_a, query_cache=cache)
    request_a = QueryRequest(
        query="shared query text",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "alice"},
    )
    response_a = await service_a.execute_query(request_a)
    assert [r.chunk_id for r in response_a.results] == ["c1"]

    results_b = [_result("c2", meta={"owner": "bob"})]
    service_b = _make_service(results_b, query_cache=cache)
    request_b = QueryRequest(
        query="shared query text",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "bob"},
    )
    response_b = await service_b.execute_query(request_b)

    service_b._execute_bm25_query.assert_awaited()  # not served from A's cache
    assert [r.chunk_id for r in response_b.results] == ["c2"]


@pytest.mark.asyncio
async def test_cache_key_separates_by_domains_no_cross_contamination() -> None:
    cache = QueryCacheService(ttl=60, max_size=10)

    results_a = [_result("c1", domain="home-assistant")]
    service_a = _make_service(results_a, query_cache=cache)
    request_a = QueryRequest(
        query="shared query text",
        mode=QueryMode.BM25,
        top_k=5,
        domains=["home-assistant"],
    )
    response_a = await service_a.execute_query(request_a)
    assert [r.chunk_id for r in response_a.results] == ["c1"]

    results_b = [_result("c2", domain="billing")]
    service_b = _make_service(results_b, query_cache=cache)
    request_b = QueryRequest(
        query="shared query text", mode=QueryMode.BM25, top_k=5, domains=["billing"]
    )
    response_b = await service_b.execute_query(request_b)

    service_b._execute_bm25_query.assert_awaited()
    assert [r.chunk_id for r in response_b.results] == ["c2"]


@pytest.mark.asyncio
async def test_cache_hit_when_metadata_filter_identical() -> None:
    """Same query + same metadata_filter DOES hit cache (sanity control for
    the separation tests above — proves the key isn't over-sensitive)."""
    cache = QueryCacheService(ttl=60, max_size=10)

    results_a = [_result("c1", meta={"owner": "alice"})]
    service_a = _make_service(results_a, query_cache=cache)
    request = QueryRequest(
        query="shared query text",
        mode=QueryMode.BM25,
        top_k=5,
        metadata_filter={"owner": "alice"},
    )
    await service_a.execute_query(request)

    results_b = [_result("c2", meta={"owner": "alice"})]  # would differ if re-run
    service_b = _make_service(results_b, query_cache=cache)
    response_b = await service_b.execute_query(request)

    service_b._execute_bm25_query.assert_not_awaited()  # served from cache
    assert [r.chunk_id for r in response_b.results] == ["c1"]
