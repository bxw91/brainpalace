"""Query service for executing semantic search queries."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

# Import reranker module to trigger provider registration
import brainpalace_server.providers.reranker  # noqa: F401
from brainpalace_server.config import settings

if TYPE_CHECKING:
    from brainpalace_server.services.memory_service import MemoryService
    from brainpalace_server.services.query_cache import QueryCacheService
from brainpalace_server.config.provider_config import load_provider_settings
from brainpalace_server.config.runtime_mode import is_read_only
from brainpalace_server.indexing import EmbeddingGenerator, get_embedding_generator
from brainpalace_server.indexing.bm25_index import BM25IndexManager, get_bm25_manager
from brainpalace_server.indexing.graph_index import (
    GraphIndexManager,
    get_graph_index_manager,
)
from brainpalace_server.models import (
    QueryMode,
    QueryRequest,
    QueryResponse,
    QueryResult,
)
from brainpalace_server.models.query import ComputeResult
from brainpalace_server.providers import ProviderRegistry
from brainpalace_server.storage import (
    StorageBackendProtocol,
    VectorStoreManager,
    get_storage_backend,
    get_vector_store,
)

logger = logging.getLogger(__name__)


def _decay_half_life() -> float:
    """Time-decay half-life in days, coerced to a real float.

    Returns 0.0 (decay disabled) when the setting is non-numeric — e.g. tests
    that patch ``settings`` with a MagicMock. Mirrors the ``ENABLE_RERANKING``
    isinstance guard in ``execute_query``.
    """
    half = getattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 90.0)
    if isinstance(half, bool) or not isinstance(half, (int, float)):
        return 0.0
    return float(half)


def _stale_decision_penalty() -> float:
    """Stale-decision ranking multiplier (Phase 140), coerced to a real float.

    Returns 1.0 (no penalty) for non-numeric settings — e.g. MagicMock-patched
    test settings. Mirrors ``_decay_half_life``.
    """
    p = getattr(settings, "BRAINPALACE_STALE_DECISION_PENALTY", 0.5)
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        return 1.0
    return float(p)


#: Chunk source types produced by each optional session feature. When the
#: feature is OFF its data is HIDDEN from search (hard off, no per-query
#: override) — a disabled feature must not leak possibly-stale data.
_VECTOR_SESSION_TYPES = ("session_turn",)
_SUMMARY_SESSION_TYPES = ("session_summary", "session_decision")


def hidden_session_source_types() -> set[str]:
    """Source types to suppress from results given the live recall flags.

    Resolves :func:`session_recall_flags` (fails OPEN ⇒ empty set). Vector
    indexing OFF hides raw ``session_turn`` chunks; summarization OFF hides
    ``session_summary`` / ``session_decision`` chunks. Channel-agnostic: callers
    apply it as a Chroma ``$nin`` (vector/hybrid) AND a post-filter (covers
    bm25, which can only include-list source types).
    """
    from brainpalace_server.config.session_config import session_recall_flags

    vector_on, summarization_on = session_recall_flags()
    hidden: set[str] = set()
    if not vector_on:
        hidden.update(_VECTOR_SESSION_TYPES)
    if not summarization_on:
        hidden.update(_SUMMARY_SESSION_TYPES)
    return hidden


def _parse_created_at(value: Any) -> datetime | None:
    """Parse a chunk's ``created_at`` metadata into a tz-aware UTC datetime.

    Returns None on missing/unparseable values (caller applies no penalty).
    Naive timestamps are treated as UTC.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class VectorManagerRetriever(BaseRetriever):
    """LlamaIndex retriever wrapper for storage backend vector search."""

    def __init__(
        self,
        service: QueryService,
        top_k: int,
        threshold: float,
    ):
        super().__init__()
        self.service = service
        self.top_k = top_k
        self.threshold = threshold

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        # Synchronous retrieve not supported, use aretrieve
        return []

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query_embedding = await self.service.embedding_generator.embed_query(
            query_bundle.query_str
        )
        results = await self.service.storage_backend.vector_search(
            query_embedding=query_embedding,
            top_k=self.top_k,
            similarity_threshold=self.threshold,
        )
        return [
            NodeWithScore(
                node=TextNode(text=res.text, id_=res.chunk_id, metadata=res.metadata),
                score=res.score,
            )
            for res in results
        ]


class QueryService:
    """
    Executes semantic, keyword, and hybrid search queries.

    Coordinates embedding generation, vector similarity search,
    and BM25 retrieval with result fusion.
    """

    def __init__(
        self,
        vector_store: VectorStoreManager | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        bm25_manager: BM25IndexManager | None = None,
        graph_index_manager: GraphIndexManager | None = None,
        storage_backend: StorageBackendProtocol | None = None,
        query_cache: QueryCacheService | None = None,
        memory_service: MemoryService | None = None,
        record_store: object | None = None,
    ):
        """
        Initialize the query service.

        Args:
            vector_store: [DEPRECATED] Vector store manager
                (for backward compat).
            embedding_generator: Embedding generator instance.
            bm25_manager: [DEPRECATED] BM25 index manager
                (for backward compat).
            graph_index_manager: Graph index manager instance (Feature 113).
            storage_backend: Storage backend implementing protocol (preferred).
        """
        # Resolve storage_backend with backward compatibility
        if storage_backend is not None:
            self.storage_backend = storage_backend
        elif vector_store is not None or bm25_manager is not None:
            # Legacy path: wrap provided stores in ChromaBackend
            from brainpalace_server.storage.chroma.backend import ChromaBackend

            self.storage_backend = ChromaBackend(
                vector_store=vector_store,
                bm25_manager=bm25_manager,
            )
        else:
            # New path: use factory
            self.storage_backend = get_storage_backend()

        # Maintain backward-compatible aliases for code that accesses them directly
        # Extract from ChromaBackend if possible, otherwise set to None
        if hasattr(self.storage_backend, "vector_store"):
            self.vector_store = self.storage_backend.vector_store
        else:
            self.vector_store = vector_store or get_vector_store()

        if hasattr(self.storage_backend, "bm25_manager"):
            self.bm25_manager = self.storage_backend.bm25_manager
        else:
            self.bm25_manager = bm25_manager or get_bm25_manager()

        self.embedding_generator = embedding_generator or get_embedding_generator()
        self.graph_index_manager = graph_index_manager or get_graph_index_manager()
        self.query_cache = query_cache
        self.memory_service = memory_service
        self.record_store = record_store  # Task 9: stored for Task 11 executor

    def is_ready(self) -> bool:
        """
        Check if the service is ready to process queries.

        Returns:
            True if the storage backend is initialized and has documents.
        """
        return self.storage_backend.is_initialized

    async def execute_query(self, request: QueryRequest) -> QueryResponse:
        """
        Execute a search query based on the requested mode.

        Supports optional two-stage reranking when ENABLE_RERANKING=True,
        or per-request via ``request.rerank`` (True forces, False disables,
        None follows the setting).
        Stage 1: Broad retrieval with expanded top_k
        Stage 2: Cross-encoder reranking for precision

        Args:
            request: QueryRequest with query text and parameters.

        Returns:
            QueryResponse with ranked results.

        Raises:
            RuntimeError: If the service is not ready.
        """
        if not self.is_ready():
            raise RuntimeError(
                "Query service not ready. Please wait for indexing to complete."
            )

        start_time = time.time()

        # Query cache check (Phase 17 — QCACHE-01, QCACHE-03)
        from brainpalace_server.services.query_cache import (
            QueryCacheService,
        )

        # Time-decay (Phase 110): decayed scores drift negligibly over the cache
        # TTL (default 1h) given the day-scale half-life, so we cache them — but
        # the time_decay flag is part of the cache key so decay-on and
        # --no-time-decay results never collide.
        decay_active = _decay_half_life() > 0 and getattr(request, "time_decay", True)

        cache = self.query_cache
        cache_key: str | None = None
        if cache is not None and QueryCacheService.is_cacheable_mode(
            request.mode.value
        ):
            cache_params: dict[str, Any] = {
                "query": request.query,
                "mode": request.mode.value,
                "top_k": request.top_k,
                "similarity_threshold": request.similarity_threshold,
                "alpha": request.alpha,
                "time_decay": decay_active,
                "rerank": request.rerank,
                "source_types": sorted(request.source_types or []),
                "languages": sorted(request.languages or []),
                "file_paths": sorted(request.file_paths or []),
                "language": request.language,
            }
            cache_key = cache.make_cache_key(cache_params)
            cached = cache.get(cache_key)
            if cached is not None:
                # Memory boost is layered fresh per call (not cached), so a
                # cache hit still reflects current curated memory.
                return await self._apply_memory_boost(request, cached)

        # Early return for empty index — avoids top_k=0 errors downstream
        corpus_size = await self.storage_backend.get_count()
        if corpus_size == 0:
            elapsed = (time.time() - start_time) * 1000
            return QueryResponse(
                results=[],
                query_time_ms=elapsed,
                total_results=0,
            )

        # Determine if reranking is enabled
        # Use getattr with default False to handle mocked settings in tests
        enable_reranking = getattr(settings, "ENABLE_RERANKING", False)
        if not isinstance(enable_reranking, bool):
            enable_reranking = False
        # Per-request override (Retrieval Explorer): true forces, false disables.
        if request.rerank is not None:
            enable_reranking = request.rerank
        original_top_k = request.top_k

        # Stage 1: Adjust top_k for reranking if enabled
        if enable_reranking:
            # Calculate stage 1 candidates: top_k * multiplier, capped at max_candidates
            multiplier = getattr(settings, "RERANKER_TOP_K_MULTIPLIER", 10)
            max_candidates = getattr(settings, "RERANKER_MAX_CANDIDATES", 100)
            stage1_top_k = min(
                request.top_k * multiplier,
                max_candidates,
            )
            logger.debug(
                f"Reranking enabled: Stage 1 retrieving {stage1_top_k} candidates "
                f"for final top_k={original_top_k}"
            )
            # Create modified request with expanded top_k for Stage 1.
            # Internal over-fetch only: stage1_top_k may exceed the public
            # QueryRequest top_k<=50 ceiling (it is bounded by
            # RERANKER_MAX_CANDIDATES instead). model_copy skips validation, so
            # it does not trip the le=50 constraint and preserves every other
            # field. Stage 2 truncates back to original_top_k.
            stage1_request = request.model_copy(update={"top_k": stage1_top_k})
        else:
            stage1_request = request

        # Auto-router: when mode is HYBRID and compute tells are present, try
        # compute first. If it returns rows, return them immediately (set-level
        # answer). Empty result → no metric resolved / no rows → fall through to
        # normal hybrid retrieval (finding #4 — never return empty compute for
        # an auto-routed query).
        from brainpalace_server.services.query_router import classify_compute_intent

        auto_compute = (
            stage1_request.mode == QueryMode.HYBRID
            and getattr(settings, "ENABLE_COMPUTE", True)
            and getattr(self, "record_store", None) is not None
            and classify_compute_intent(stage1_request.query)
        )
        if auto_compute:
            compute_results = await self._execute_compute_query(stage1_request)
            if compute_results:
                elapsed = (time.time() - start_time) * 1000
                return QueryResponse(
                    results=[],
                    compute=compute_results,
                    query_time_ms=elapsed,
                    total_results=len(compute_results),
                )
            # empty → fall through to normal hybrid retrieval (finding #4)

        # Read-only: vector/hybrid/multi need to embed the query text (a
        # provider call). On a cache miss, degrade to BM25 (purely lexical, no
        # network) so the server stays queryable offline. GRAPH and BM25 are
        # unaffected. Cached vector/hybrid results are still served — this runs
        # only after the cache-miss path.
        if is_read_only() and stage1_request.mode in (
            QueryMode.VECTOR,
            QueryMode.HYBRID,
            QueryMode.MULTI,
        ):
            logger.info(
                "read-only: %s query degraded to bm25 (no embed_query)",
                stage1_request.mode.value,
            )
            stage1_request = stage1_request.model_copy(update={"mode": QueryMode.BM25})

        # Compute early-return: aggregation rows are not documents — skip the
        # entire retrieval tail (content-filter, hidden-source filter, time-decay,
        # rerank, truncate). Privacy is preserved because _execute_compute_query
        # applies exclude_sources internally.
        if stage1_request.mode == QueryMode.COMPUTE:
            compute_rows = await self._execute_compute_query(stage1_request)
            elapsed = (time.time() - start_time) * 1000
            return QueryResponse(
                results=[],
                compute=compute_rows,
                query_time_ms=elapsed,
                total_results=len(compute_rows),
            )

        # Execute Stage 1 retrieval
        if stage1_request.mode == QueryMode.BM25:
            results = await self._execute_bm25_query(stage1_request)
        elif stage1_request.mode == QueryMode.VECTOR:
            results = await self._execute_vector_query(stage1_request)
        elif stage1_request.mode == QueryMode.GRAPH:
            results = await self._execute_graph_query(stage1_request)
        elif stage1_request.mode == QueryMode.MULTI:
            results = await self._execute_multi_query(stage1_request)
        else:  # HYBRID
            results = await self._execute_hybrid_query(stage1_request)

        # Apply content filters if specified
        if any([request.source_types, request.languages, request.file_paths]):
            results = self._filter_results(results, request)

        # Hard-off session recall: drop chunks whose producing feature is
        # disabled (channel-agnostic — also covers bm25, which the where-clause
        # cannot exclude). A disabled feature's possibly-stale data is never
        # returned, even with an explicit source_types request.
        hidden = hidden_session_source_types()
        if hidden:
            results = [
                r for r in results if getattr(r, "source_type", None) not in hidden
            ]

        # Time-decay (Phase 110): age-weight before rerank/truncate so newer
        # chunks survive into top_k. No-op when disabled.
        if decay_active:
            results = self._apply_time_decay(results, request)

        # Stale-decision penalty (Phase 140): down-rank superseded decisions.
        # Self-guards (no-op at penalty 1.0 / no graph / simple backend).
        results = self._apply_stale_decision_penalty(results)

        # Stage 2: Apply reranking if enabled and we have more results than requested
        if enable_reranking and len(results) > original_top_k:
            results = await self._rerank_results(
                results=results,
                query=request.query,
                top_k=original_top_k,
            )
        elif enable_reranking:
            # Not enough results to warrant reranking, just truncate
            logger.debug(
                f"Skipping reranking: only {len(results)} results, "
                f"need more than {original_top_k}"
            )
            results = results[:original_top_k]
        # else: reranking disabled, results already at correct size

        query_time_ms = (time.time() - start_time) * 1000

        logger.debug(
            f"Query ({request.mode}) '{request.query[:50]}...' returned "
            f"{len(results)} results in {query_time_ms:.2f}ms"
            f"{' (reranked)' if enable_reranking else ''}"
        )

        response = QueryResponse(
            results=results,
            query_time_ms=query_time_ms,
            total_results=len(results),
        )

        # Store in query cache (Phase 17 — QCACHE-01). Cache the memory-free
        # base response; memory is layered fresh below so it never goes stale.
        if cache is not None and cache_key is not None:
            await cache.put(cache_key, response)

        return await self._apply_memory_boost(request, response)

    def _apply_time_decay(
        self, results: list[QueryResult], request: QueryRequest
    ) -> list[QueryResult]:
        """Multiply each result's score by an exponential age factor (Phase 110).

        factor = 0.5 ** (age_days / half_life). Newer chunks rank higher.
        No-op when the half-life is <= 0 or ``request.time_decay`` is False.
        Results with a missing/unparseable ``created_at`` get no penalty.
        Re-sorts by the decayed score (descending).
        """
        half = _decay_half_life()
        if half <= 0 or getattr(request, "time_decay", True) is False:
            return results

        now = datetime.now(timezone.utc)
        for r in results:
            created = _parse_created_at((r.metadata or {}).get("created_at"))
            if created is None:
                continue
            age_days = max(0.0, (now - created).total_seconds() / 86400.0)
            r.score *= 0.5 ** (age_days / half)

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _apply_stale_decision_penalty(
        self, results: list[QueryResult]
    ) -> list[QueryResult]:
        """Down-rank `session_decision` results whose decision is superseded.

        A decision is stale when its node is the subject of a currently-valid
        `superseded-by` edge (temporal graph, Phase 090/140). Best-effort: no-op
        when the penalty is 1.0, the graph is unavailable, or the backend lacks
        the temporal surface. Re-sorts only if something changed.
        """
        penalty = _stale_decision_penalty()
        if penalty >= 1.0:
            return results
        gm = getattr(self, "graph_index_manager", None)
        graph = getattr(gm, "graph_store", None) if gm is not None else None
        if graph is None or not hasattr(graph, "timeline"):
            return results

        changed = False
        for r in results:
            if getattr(r, "source_type", None) != "session_decision":
                continue
            name = (r.text or "").split("\n", 1)[0].strip()
            if not name:
                continue
            try:
                stale = any(
                    e.get("predicate") == "superseded-by"
                    and e.get("valid")
                    and (e.get("subject") or "").strip().lower() == name.lower()
                    for e in graph.timeline(name)
                )
            except Exception:  # noqa: BLE001 — best-effort
                stale = False
            if stale:
                r.score *= penalty
                changed = True
        if changed:
            results.sort(key=lambda r: r.score, reverse=True)
        return results

    async def _apply_memory_boost(
        self, request: QueryRequest, response: QueryResponse
    ) -> QueryResponse:
        """Merge relevant curated memories into a response (Phase 030).

        Returns a NEW QueryResponse (never mutates the input, which may be a
        cached instance). No-op when memory is disabled/absent, the request
        opted out, the mode is pure bm25, or no memory clears the score floor.
        """
        ms = self.memory_service
        if ms is None or not getattr(request, "use_memory", True):
            return response
        if request.mode == QueryMode.BM25:
            return response
        if not getattr(settings, "MEMORY_ENABLED", True):
            return response

        try:
            hits, _ = await ms.recall(
                request.query, top_k=getattr(settings, "MEMORY_RECALL_K", 3)
            )
        except Exception as exc:  # noqa: BLE001 — boost must never break a query
            logger.warning("memory boost recall failed: %s", exc)
            return response

        # Hard-off session recall: when summarization is disabled, hide
        # auto-promoted session-derived memory (origin != "user") — keep only
        # manually-saved `brainpalace remember` facts. MemoryHit carries no
        # origin, so cross-reference the stored entries by id.
        from brainpalace_server.config.session_config import session_recall_flags

        _, summarization_on = session_recall_flags()
        user_only_ids: set[str] | None = None
        if not summarization_on:
            try:
                user_only_ids = {
                    m.id for m in ms.load() if (m.origin or "user") == "user"
                }
            except Exception as exc:  # noqa: BLE001 — fail open, never break a query
                logger.warning("memory origin filter skipped: %s", exc)
                user_only_ids = None

        boost = getattr(settings, "MEMORY_BOOST", 1.5)
        floor = getattr(settings, "MEMORY_MIN_SCORE", 0.35)
        existing = {r.chunk_id for r in response.results}
        mem_results: list[QueryResult] = []
        for h in hits:
            if h.score < floor or h.id in existing:
                continue
            if user_only_ids is not None and h.id not in user_only_ids:
                continue
            mem_results.append(
                QueryResult(
                    text=h.text,
                    source=f"memory/{h.id}",
                    score=h.score * boost,
                    vector_score=h.score,
                    chunk_id=h.id,
                    source_type="memory",
                    metadata={
                        "section": h.section,
                        "tags": h.tags,
                        "origin": "memory",
                    },
                )
            )
        if not mem_results:
            return response

        merged = sorted(
            mem_results + list(response.results),
            key=lambda r: r.score,
            reverse=True,
        )[: request.top_k]
        return QueryResponse(
            results=merged,
            query_time_ms=response.query_time_ms,
            total_results=len(merged),
        )

    async def _execute_vector_query(self, request: QueryRequest) -> list[QueryResult]:
        """Execute pure semantic search."""
        query_embedding = await self.embedding_generator.embed_query(request.query)
        where_clause = self._build_where_clause(request.source_types, request.languages)
        search_results = await self.storage_backend.vector_search(
            query_embedding=query_embedding,
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            where=where_clause,
        )

        return [
            QueryResult(
                text=res.text,
                source=res.metadata.get(
                    "source", res.metadata.get("file_path", "unknown")
                ),
                score=res.score,
                vector_score=res.score,
                chunk_id=res.chunk_id,
                source_type=res.metadata.get("source_type", "doc"),
                language=res.metadata.get("language"),
                metadata={
                    k: v
                    for k, v in res.metadata.items()
                    if k not in ("source", "file_path", "source_type", "language")
                },
            )
            for res in search_results
        ]

    async def _execute_bm25_query(self, request: QueryRequest) -> list[QueryResult]:
        """Execute pure keyword search."""
        if not self.bm25_manager.is_initialized:
            raise RuntimeError("BM25 index not initialized")

        # Use storage backend's keyword_search (scores already normalized 0-1)
        search_results = await self.storage_backend.keyword_search(
            query=request.query,
            top_k=request.top_k,
            source_types=request.source_types,
            languages=request.languages,
            language=request.language,
        )

        return [
            QueryResult(
                text=res.text,
                source=res.metadata.get(
                    "source", res.metadata.get("file_path", "unknown")
                ),
                score=res.score,
                bm25_score=res.score,  # Already normalized 0-1
                chunk_id=res.chunk_id,
                source_type=res.metadata.get("source_type", "doc"),
                language=res.metadata.get("language"),
                metadata={
                    k: v
                    for k, v in res.metadata.items()
                    if k not in ("source", "file_path", "source_type", "language")
                },
            )
            for res in search_results
        ]

    async def _execute_hybrid_query(self, request: QueryRequest) -> list[QueryResult]:
        """Execute hybrid search using Relative Score Fusion."""
        # For US5, we want to provide individual scores.
        # We'll perform the individual searches first to get the scores.

        # Get corpus size to avoid requesting more than available
        corpus_size = await self.storage_backend.get_count()
        effective_top_k = min(request.top_k, corpus_size)

        # Build ChromaDB where clause for filtering
        where_clause = self._build_where_clause(request.source_types, request.languages)

        # 1. Vector Search
        query_embedding = await self.embedding_generator.embed_query(request.query)
        vector_results = await self.storage_backend.vector_search(
            query_embedding=query_embedding,
            top_k=effective_top_k,
            similarity_threshold=request.similarity_threshold,
            where=where_clause,
        )

        # 2. BM25 Search (scores already normalized 0-1 by ChromaBackend)
        bm25_search_results = []
        if self.bm25_manager.is_initialized:
            # Use storage backend's keyword_search
            # (returns SearchResult with normalized scores)
            bm25_search_results = await self.storage_backend.keyword_search(
                query=request.query,
                top_k=effective_top_k,
                source_types=request.source_types,
                languages=request.languages,
                language=request.language,
            )

        # Convert BM25 SearchResults to QueryResults
        bm25_query_results = []
        for res in bm25_search_results:
            bm25_query_results.append(
                QueryResult(
                    text=res.text,
                    source=res.metadata.get(
                        "source", res.metadata.get("file_path", "unknown")
                    ),
                    score=res.score,  # Already normalized 0-1
                    bm25_score=res.score,
                    chunk_id=res.chunk_id,
                    source_type=res.metadata.get("source_type", "doc"),
                    language=res.metadata.get("language"),
                    metadata={
                        k: v
                        for k, v in res.metadata.items()
                        if k not in ("source", "file_path", "source_type", "language")
                    },
                )
            )

        # 3. Simple hybrid fusion for small corpora
        # Combine vector and BM25 results manually to avoid retriever complexity

        # Score normalization: both already in 0-1 range from backend
        # Vector scores are cosine similarity (0-1)
        # BM25 scores are normalized to 0-1 by ChromaBackend.keyword_search
        max_vector_score = max((r.score for r in vector_results), default=1.0) or 1.0
        max_bm25_score = (
            max((r.bm25_score or 0.0 for r in bm25_query_results), default=1.0) or 1.0
        )

        # Create combined results map
        combined_results: dict[str, dict[str, Any]] = {}

        # Add vector results (convert SearchResult to QueryResult)
        for res in vector_results:
            query_result = QueryResult(
                text=res.text,
                source=res.metadata.get(
                    "source", res.metadata.get("file_path", "unknown")
                ),
                score=res.score,
                vector_score=res.score,
                chunk_id=res.chunk_id,
                source_type=res.metadata.get("source_type", "doc"),
                language=res.metadata.get("language"),
                metadata={
                    k: v
                    for k, v in res.metadata.items()
                    if k not in ("source", "file_path", "source_type", "language")
                },
            )
            combined_results[res.chunk_id] = {
                "result": query_result,
                "vector_score": res.score / max_vector_score,
                "bm25_score": 0.0,
                "total_score": request.alpha * (res.score / max_vector_score),
            }

        # Add/merge BM25 results
        for bm25_res in bm25_query_results:
            chunk_id = bm25_res.chunk_id
            bm25_normalized = (bm25_res.bm25_score or 0.0) / max_bm25_score
            bm25_weighted = (1.0 - request.alpha) * bm25_normalized

            if chunk_id in combined_results:
                combined_results[chunk_id]["bm25_score"] = bm25_normalized
                combined_results[chunk_id]["total_score"] += bm25_weighted
                # Update BM25 score on existing result
                combined_results[chunk_id]["result"].bm25_score = bm25_res.bm25_score
            else:
                combined_results[chunk_id] = {
                    "result": bm25_res,
                    "vector_score": 0.0,
                    "bm25_score": bm25_normalized,
                    "total_score": bm25_weighted,
                }

        # Convert to final results
        fused_nodes = []
        for _chunk_id, data in combined_results.items():
            result = data["result"]
            # Update score with combined score
            result.score = data["total_score"]
            fused_nodes.append(result)

        # Sort by combined score and take top_k
        fused_nodes.sort(key=lambda x: x.score, reverse=True)
        fused_nodes = fused_nodes[: request.top_k]

        return fused_nodes

    async def _execute_graph_query(
        self,
        request: QueryRequest,
        traversal_depth: int = 2,
    ) -> list[QueryResult]:
        """Execute graph-only query using entity relationships.

        Uses the knowledge graph to find documents related to
        entities mentioned in the query.

        Args:
            request: Query request.
            traversal_depth: How many hops to traverse in graph.

        Returns:
            List of QueryResult from graph retrieval.

        Raises:
            ValueError: If GraphRAG is not enabled or backend is incompatible.
        """
        # Check backend compatibility for graph queries
        from brainpalace_server.storage import get_effective_backend_type

        backend_type = get_effective_backend_type()
        if backend_type != "chroma":
            raise ValueError(
                f"Graph queries (mode='graph') require ChromaDB backend. "
                f"Current backend: '{backend_type}'. "
                f"To use graph queries, set BRAINPALACE_STORAGE_BACKEND=chroma."
            )

        if not settings.ENABLE_GRAPH_INDEX:
            raise ValueError(
                "GraphRAG not enabled. Set ENABLE_GRAPH_INDEX=true in environment."
            )

        # Get filter parameters (use getattr for backward compat with test mocks)
        entity_types = getattr(request, "entity_types", None)
        relationship_types = getattr(request, "relationship_types", None)

        # Query the graph for related entities (with type filters if provided)
        if entity_types or relationship_types:
            graph_results = self.graph_index_manager.query_by_type(
                query_text=request.query,
                entity_types=entity_types,
                relationship_types=relationship_types,
                top_k=request.top_k,
                traversal_depth=traversal_depth,
            )
        else:
            graph_results = self.graph_index_manager.query(
                query_text=request.query,
                top_k=request.top_k,
                traversal_depth=traversal_depth,
            )

        if not graph_results:
            logger.debug("No graph results found, falling back to vector search")
            return await self._execute_vector_query(request)

        # Convert graph results to QueryResults
        results: list[QueryResult] = []
        chunk_ids = [
            r.get("source_chunk_id") for r in graph_results if r.get("source_chunk_id")
        ]

        if not chunk_ids:
            # No source chunks in graph, fall back to vector search
            return await self._execute_vector_query(request)

        # Look up the actual documents from vector store
        for graph_result in graph_results:
            chunk_id = graph_result.get("source_chunk_id")
            if not chunk_id:
                continue

            # Get document from storage backend by ID
            try:
                doc = await self.storage_backend.get_by_id(chunk_id)
                if doc:
                    result = QueryResult(
                        text=doc.get("text", ""),
                        source=doc.get("metadata", {}).get(
                            "source",
                            doc.get("metadata", {}).get("file_path", "unknown"),
                        ),
                        score=graph_result.get("graph_score", 0.5),
                        graph_score=graph_result.get("graph_score", 0.5),
                        chunk_id=chunk_id,
                        source_type=doc.get("metadata", {}).get("source_type", "doc"),
                        language=doc.get("metadata", {}).get("language"),
                        related_entities=[
                            graph_result.get("subject", ""),
                            graph_result.get("object", ""),
                        ],
                        relationship_path=[graph_result.get("relationship_path", "")],
                        metadata={
                            k: v
                            for k, v in doc.get("metadata", {}).items()
                            if k
                            not in ("source", "file_path", "source_type", "language")
                        },
                    )
                    results.append(result)
            except Exception as e:
                logger.debug(f"Failed to retrieve chunk {chunk_id}: {e}")
                continue

        # If no results from graph, fall back to vector search
        if not results:
            logger.debug("No documents found from graph, falling back to vector search")
            return await self._execute_vector_query(request)

        return results[: request.top_k]

    async def _execute_compute_query(  # noqa: E501
        self, request: QueryRequest
    ) -> list[ComputeResult]:
        """Execute a compute (set-level aggregation) query over typed Records.

        Returns an empty list when compute is disabled, no RecordStore is
        attached, no metric resolves, or the store is empty — callers (auto-
        router) treat empty as a signal to fall back to normal hybrid retrieval.
        Explicit mode=compute returns the empty list directly (no fallback).
        """
        from brainpalace_server.config import settings as _settings
        from brainpalace_server.models.query import ComputeResult
        from brainpalace_server.services.compute_compiler import compile_compute

        if not getattr(_settings, "ENABLE_COMPUTE", True):
            return []
        rs = getattr(self, "record_store", None)
        if rs is None:
            return []
        plan = compile_compute(
            request.query, rs.distinct_metrics(), rs.distinct_subjects()
        )
        if plan is None:
            return []
        exclude = ["session"] if hidden_session_source_types() else None
        rows = rs.aggregate(
            metric=plan.metric,
            op=plan.op,
            group_by=plan.group_by,
            order=plan.order,
            limit=plan.limit,
            since=plan.since,
            until=plan.until,
            min_confidence=getattr(_settings, "COMPUTE_MIN_CONFIDENCE", 0.7),
            exclude_sources=exclude,
        )
        maxv = max((abs(v) for _, v in rows), default=1.0) or 1.0
        out = []
        for gk, v in rows:
            label = str(gk) if gk is not None else f"{plan.metric} {plan.op}"
            out.append(
                ComputeResult(
                    label=label,
                    value=float(v),
                    metric=plan.metric,
                    op=plan.op,
                    group=gk,
                    score=abs(float(v)) / maxv,
                )
            )
        return out

    async def _execute_multi_query(self, request: QueryRequest) -> list[QueryResult]:
        """Execute multi-retrieval query combining vector, BM25, and graph.

        Uses Reciprocal Rank Fusion (RRF) to combine results from
        all three retrieval methods.

        Args:
            request: Query request.

        Returns:
            List of QueryResult with combined scores.
        """
        # Get results from each retriever
        vector_results = await self._execute_vector_query(request)
        bm25_results = await self._execute_bm25_query(request)

        # Get graph results if enabled and backend supports it
        graph_results: list[QueryResult] = []
        from brainpalace_server.storage import get_effective_backend_type

        backend_type = get_effective_backend_type()
        if settings.ENABLE_GRAPH_INDEX and backend_type == "chroma":
            try:
                graph_results = await self._execute_graph_query(request)
            except ValueError:
                pass  # Graph not enabled or not available, skip
        elif backend_type != "chroma":
            logger.info(
                "Graph component skipped in multi-mode: "
                "graph queries require ChromaDB backend "
                f"(current: {backend_type})"
            )

        # Apply Reciprocal Rank Fusion
        rrf_k = settings.GRAPH_RRF_K  # Typical value is 60
        combined_scores: dict[str, dict[str, Any]] = {}

        # Process vector results
        for rank, result in enumerate(vector_results):
            chunk_id = result.chunk_id
            rrf_score = 1.0 / (rrf_k + rank + 1)
            if chunk_id not in combined_scores:
                combined_scores[chunk_id] = {
                    "result": result,
                    "rrf_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "graph_rank": None,
                }
            combined_scores[chunk_id]["rrf_score"] += rrf_score
            combined_scores[chunk_id]["vector_rank"] = rank + 1

        # Process BM25 results
        for rank, result in enumerate(bm25_results):
            chunk_id = result.chunk_id
            rrf_score = 1.0 / (rrf_k + rank + 1)
            if chunk_id not in combined_scores:
                combined_scores[chunk_id] = {
                    "result": result,
                    "rrf_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "graph_rank": None,
                }
            combined_scores[chunk_id]["rrf_score"] += rrf_score
            combined_scores[chunk_id]["bm25_rank"] = rank + 1

        # Process graph results
        for rank, result in enumerate(graph_results):
            chunk_id = result.chunk_id
            rrf_score = 1.0 / (rrf_k + rank + 1)
            if chunk_id not in combined_scores:
                combined_scores[chunk_id] = {
                    "result": result,
                    "rrf_score": 0.0,
                    "vector_rank": None,
                    "bm25_rank": None,
                    "graph_rank": None,
                }
            combined_scores[chunk_id]["rrf_score"] += rrf_score
            combined_scores[chunk_id]["graph_rank"] = rank + 1
            # Preserve graph-specific fields
            if result.related_entities:
                combined_scores[chunk_id][
                    "result"
                ].related_entities = result.related_entities
            if result.relationship_path:
                combined_scores[chunk_id][
                    "result"
                ].relationship_path = result.relationship_path
            if result.graph_score:
                combined_scores[chunk_id]["result"].graph_score = result.graph_score

        # Sort by RRF score and take top_k
        sorted_results = sorted(
            combined_scores.values(),
            key=lambda x: x["rrf_score"],
            reverse=True,
        )

        # Update scores and return
        final_results: list[QueryResult] = []
        for data in sorted_results[: request.top_k]:
            result = data["result"]
            result.score = data["rrf_score"]
            final_results.append(result)

        return final_results

    async def get_document_count(self) -> int:
        """
        Get the total number of indexed documents.

        Returns:
            Number of documents in the vector store.
        """
        if not self.is_ready():
            return 0
        return await self.storage_backend.get_count()

    def _filter_results(
        self, results: list[QueryResult], request: QueryRequest
    ) -> list[QueryResult]:
        """
        Filter query results based on request parameters.

        Args:
            results: List of query results to filter.
            request: Query request with filter parameters.

        Returns:
            Filtered list of results.
        """
        filtered_results = results

        # Filter by source types
        if request.source_types:
            filtered_results = [
                r for r in filtered_results if r.source_type in request.source_types
            ]

        # Filter by languages
        if request.languages:
            filtered_results = [
                r
                for r in filtered_results
                if r.language and r.language in request.languages
            ]

        # Filter by file paths (with wildcard support)
        if request.file_paths:
            import fnmatch

            filtered_results = [
                r
                for r in filtered_results
                if any(
                    fnmatch.fnmatch(r.source, pattern) for pattern in request.file_paths
                )
            ]

        return filtered_results

    def _build_where_clause(
        self, source_types: list[str] | None, languages: list[str] | None
    ) -> dict[str, Any] | None:
        """
        Build ChromaDB where clause from filter parameters.

        Args:
            source_types: List of source types to filter by.
            languages: List of languages to filter by.

        Returns:
            ChromaDB where clause dict or None.
        """
        conditions: list[dict[str, Any]] = []

        if source_types:
            if len(source_types) == 1:
                conditions.append({"source_type": source_types[0]})
            else:
                conditions.append({"source_type": {"$in": source_types}})

        # Hard-off session recall: exclude source types whose producing feature
        # is disabled, so the vector/hybrid fetch never surfaces them. The
        # execute_query post-filter covers bm25 and is the authority; this just
        # spares the backend returning rows we would drop.
        hidden = hidden_session_source_types()
        if hidden:
            conditions.append({"source_type": {"$nin": sorted(hidden)}})

        if languages:
            if len(languages) == 1:
                conditions.append({"language": languages[0]})
            else:
                conditions.append({"language": {"$in": languages}})

        if not conditions:
            return None
        elif len(conditions) == 1:
            return conditions[0]
        else:
            return {"$and": conditions}

    async def _rerank_results(
        self,
        results: list[QueryResult],
        query: str,
        top_k: int,
    ) -> list[QueryResult]:
        """Rerank results using a cross-encoder model.

        Two-stage retrieval: Stage 1 returns broad candidates, Stage 2 reranks
        using a more accurate cross-encoder model.

        Args:
            results: List of QueryResult from Stage 1 retrieval.
            query: The original query text.
            top_k: Number of final results to return.

        Returns:
            Reranked list of QueryResult with updated scores and reranking metadata.
            Falls back to original results (truncated to top_k) on any failure.
        """
        if not results:
            return results

        start_time = time.time()

        try:
            # Get reranker configuration
            provider_settings = load_provider_settings()
            reranker = ProviderRegistry.get_reranker_provider(
                provider_settings.reranker
            )

            # Check if reranker is available
            if not reranker.is_available():
                logger.warning(
                    f"Reranker {reranker.provider_name} not available, "
                    "falling back to stage 1 results"
                )
                return results[:top_k]

            # Extract document texts for reranking
            documents = [r.text for r in results]

            # Perform reranking
            reranked = await reranker.rerank(
                query=query,
                documents=documents,
                top_k=top_k,
            )

            # If reranker returned nothing, fall back gracefully
            if not reranked:
                logger.warning(
                    "Reranker returned no results, falling back to stage 1 results"
                )
                return results[:top_k]

            # Build reranked results with updated scores and metadata
            reranked_results: list[QueryResult] = []
            for original_index, rerank_score in reranked:
                result = results[original_index]
                # Create new result with reranking metadata
                reranked_result = QueryResult(
                    text=result.text,
                    source=result.source,
                    score=rerank_score,  # Update main score to rerank score
                    vector_score=result.vector_score,
                    bm25_score=result.bm25_score,
                    chunk_id=result.chunk_id,
                    source_type=result.source_type,
                    language=result.language,
                    graph_score=result.graph_score,
                    related_entities=result.related_entities,
                    relationship_path=result.relationship_path,
                    rerank_score=rerank_score,
                    original_rank=original_index + 1,  # 1-indexed
                    metadata=result.metadata,
                )
                reranked_results.append(reranked_result)

            rerank_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Reranked {len(results)} -> {len(reranked_results)} results "
                f"in {rerank_time_ms:.2f}ms using {reranker.provider_name}"
            )

            return reranked_results

        except ModuleNotFoundError as e:
            # The local cross-encoder reranker's deps (sentence-transformers /
            # PyTorch) are an opt-in extra and are not bundled in the base
            # install. Degrade to stage-1 rather than failing the query, and tell
            # the operator exactly how to enable it (or switch to ollama).
            rerank_time_ms = (time.time() - start_time) * 1000
            logger.warning(
                "Local reranker unavailable (%s) after %.2fms — returning "
                "stage-1 results. Install it with "
                "`pip install brainpalace-rag[reranker-local]` (~2.8 GB) or set "
                "the reranker provider to 'ollama'.",
                e,
                rerank_time_ms,
            )
            return results[:top_k]
        except Exception as e:
            rerank_time_ms = (time.time() - start_time) * 1000
            logger.warning(
                f"Reranking failed after {rerank_time_ms:.2f}ms: {e}, "
                "falling back to stage 1 results"
            )
            # Graceful fallback: return stage 1 results truncated to top_k
            return results[:top_k]


# Singleton instance
_query_service: QueryService | None = None


def get_query_service() -> QueryService:
    """Get the global query service instance."""
    global _query_service
    if _query_service is None:
        _query_service = QueryService()
    return _query_service
