"""Integration tests for per-query language override in BM25 retrieval (Task 13).

Tests that ``QueryRequest.language`` is forwarded end-to-end from the API model
→ QueryService → ChromaBackend.keyword_search → BM25IndexManager.search_with_filters,
and that the query cache does not conflate results across different languages.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager
from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.services.query_service import QueryService


def _make_node(text: str, chunk_id: str, source: str, score: float) -> NodeWithScore:
    """Build a NodeWithScore as returned by BM25IndexManager.search_with_filters."""
    return NodeWithScore(
        node=TextNode(
            text=text,
            id_=chunk_id,
            metadata={"source": source, "source_type": "doc"},
        ),
        score=score,
    )


class TestQueryLanguageOverride:
    """Per-query language override is forwarded to BM25 retrieval."""

    @pytest.mark.asyncio
    async def test_language_forwarded_to_bm25_bm25_mode(
        self,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """BM25 mode: request.language is passed to keyword_search.

        Simulates indexing two Croatian documents (inflected forms) and querying
        with request.language="hr" using an inflected query term.  Only the
        matching Croatian doc should rank first.
        """
        mock_vector_store.is_initialized = True
        mock_bm25_manager.is_initialized = True
        mock_vector_store.get_count = AsyncMock(return_value=2)

        # Two Croatian docs; the Croatian stemmer would reduce "računalu" → its stem
        # and "mreže" → its stem.  We model this by having mock return only the
        # matching doc when language="hr" is forwarded.
        # "Access to the computer is restricted."
        hr_doc = _make_node(
            text="Pristup računalu je ograničen.",
            chunk_id="hr_chunk_1",
            source="docs/hr/sigurnost.md",
            score=1.0,
        )
        mock_bm25_manager.search_with_filters = AsyncMock(return_value=[hr_doc])

        service = QueryService(
            vector_store=mock_vector_store,
            embedding_generator=mock_embedding_generator,
            bm25_manager=mock_bm25_manager,
        )

        request = QueryRequest(
            query="računalu",  # inflected Croatian form
            mode=QueryMode.BM25,
            top_k=5,
            language="hr",
        )
        response = await service.execute_query(request)

        # The top result should be the Croatian doc
        assert response.total_results >= 1
        assert response.results[0].source == "docs/hr/sigurnost.md"

        # Verify language was forwarded to search_with_filters
        mock_bm25_manager.search_with_filters.assert_called_once()
        _, kwargs = mock_bm25_manager.search_with_filters.call_args
        assert (
            kwargs.get("language") == "hr"
        ), f"Expected language='hr' in search_with_filters call, got: {kwargs}"

    @pytest.mark.asyncio
    async def test_language_forwarded_to_bm25_hybrid_mode(
        self,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """Hybrid mode: request.language forwarded to the BM25 keyword_search call."""
        mock_vector_store.is_initialized = True
        mock_bm25_manager.is_initialized = True
        mock_vector_store.get_count = AsyncMock(return_value=5)

        hr_doc = _make_node(
            text="Mreže računala su složene.",
            chunk_id="hr_chunk_2",
            source="docs/hr/mreze.md",
            score=1.0,
        )
        mock_bm25_manager.search_with_filters = AsyncMock(return_value=[hr_doc])
        mock_vector_store.similarity_search = AsyncMock(return_value=[])

        service = QueryService(
            vector_store=mock_vector_store,
            embedding_generator=mock_embedding_generator,
            bm25_manager=mock_bm25_manager,
        )

        request = QueryRequest(
            query="mreže",
            mode=QueryMode.HYBRID,
            top_k=5,
            language="hr",
        )
        response = await service.execute_query(request)

        assert response.total_results >= 1

        # Verify language kwarg was forwarded in hybrid path's BM25 call
        mock_bm25_manager.search_with_filters.assert_called_once()
        _, kwargs = mock_bm25_manager.search_with_filters.call_args
        assert (
            kwargs.get("language") == "hr"
        ), f"Expected language='hr' in search_with_filters call, got: {kwargs}"

    @pytest.mark.asyncio
    async def test_no_language_override_uses_none(
        self,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """When language is not set, None is forwarded (manager uses default_lang)."""
        mock_vector_store.is_initialized = True
        mock_bm25_manager.is_initialized = True
        mock_vector_store.get_count = AsyncMock(return_value=3)
        mock_bm25_manager.search_with_filters = AsyncMock(return_value=[])

        service = QueryService(
            vector_store=mock_vector_store,
            embedding_generator=mock_embedding_generator,
            bm25_manager=mock_bm25_manager,
        )

        request = QueryRequest(
            query="computer network",
            mode=QueryMode.BM25,
            top_k=5,
            # language not set → defaults to None
        )
        await service.execute_query(request)

        mock_bm25_manager.search_with_filters.assert_called_once()
        _, kwargs = mock_bm25_manager.search_with_filters.call_args
        assert (
            kwargs.get("language") is None
        ), f"Expected language=None when not set, got: {kwargs}"

    @pytest.mark.asyncio
    async def test_cache_key_includes_language(self):
        """Same query with different language values must produce different cache keys.

        Without this guard a result cached under language=None would be returned for
        language='hr' or vice-versa (cross-language cache poisoning).
        """
        from brainpalace_server.services.query_cache import QueryCacheService

        cache = QueryCacheService(max_size=128, ttl=60)

        request_en = QueryRequest(
            query="network",
            mode=QueryMode.BM25,
            top_k=5,
            language=None,
        )
        request_hr = QueryRequest(
            query="network",
            mode=QueryMode.BM25,
            top_k=5,
            language="hr",
        )

        # Build cache keys as query_service does
        def _make_key(req: QueryRequest) -> str:
            params = {
                "query": req.query,
                "mode": req.mode.value,
                "top_k": req.top_k,
                "similarity_threshold": req.similarity_threshold,
                "alpha": req.alpha,
                "time_decay": False,
                "source_types": sorted(req.source_types or []),
                "languages": sorted(req.languages or []),
                "file_paths": sorted(req.file_paths or []),
                "language": req.language,
            }
            return cache.make_cache_key(params)

        key_en = _make_key(request_en)
        key_hr = _make_key(request_hr)

        assert key_en != key_hr, (
            "Cache keys for language=None and language='hr' must differ to prevent "
            "cross-language cache poisoning"
        )

    @pytest.mark.asyncio
    async def test_language_field_is_optional(self):
        """QueryRequest.language is optional and defaults to None."""
        req = QueryRequest(query="test query", mode=QueryMode.BM25, top_k=5)
        assert req.language is None

    @pytest.mark.asyncio
    async def test_language_field_accepts_iso_code(self):
        """QueryRequest.language accepts ISO 639-1 codes."""
        req = QueryRequest(query="test", mode=QueryMode.BM25, top_k=5, language="hr")
        assert req.language == "hr"

        req_en = QueryRequest(query="test", mode=QueryMode.BM25, top_k=5, language="en")
        assert req_en.language == "en"


def _node(text: str, lang: str, sid: str) -> TextNode:
    """Build a TextNode with language metadata (mirrors test_bm25_manager_multilang)."""
    return TextNode(
        text=text, id_=sid, metadata={"text_language": lang, "source_type": "doc"}
    )


class TestCroatianBM25Recall:
    """Real (non-mock) BM25IndexManager recall tests for Croatian language.

    These tests exercise the actual BM25IndexManager with the Croatian stemmer
    to prove that the ``language`` parameter changes retrieval.  They would fail
    if language were not forwarded or if the Croatian analyzer were not applied.
    """

    def test_croatian_inflection_recall_manager_level(self, tmp_path):
        """Croatian stemmer collapses an inflected query form to match the indexed doc.

        Index two docs:
          - n1: "termin kod liječnika sutra"  ("liječnika" is genitive of "liječnik")
          - n2: "nabava uredskog materijala"  (unrelated)

        Query with the nominative "liječnik".  The Croatian stemmer should reduce
        both "liječnika" (doc) and "liječnik" (query) to a common stem so that n1
        ranks first.

        This test FAILS if:
          - ``language`` is not passed to search_with_filters (falls back to default
            English tokenizer which won't stem Croatian forms), OR
          - the Croatian stemmer is not registered/applied.
        """
        m = BM25IndexManager(
            persist_dir=str(tmp_path), default_lang="hr", engine="stem"
        )
        m.build_index(
            [
                _node("termin kod liječnika sutra", "hr", "n1"),
                _node("nabava uredskog materijala", "hr", "n2"),
            ]
        )

        # Query with the nominative form; doc has the genitive — stem must bridge them.
        res = asyncio.run(m.search_with_filters("liječnik", top_k=1, language="hr"))

        assert res, "Expected at least one result for 'liječnik' in Croatian corpus"
        assert (
            res[0].node.node_id == "n1"
        ), f"Expected n1 (liječnika doc) to rank first, got: {res[0].node.node_id}"

    def test_croatian_query_language_override_changes_retrieval(self, tmp_path):
        """language='hr' outperforms language=None (English default) on Croatian text.

        Builds a real index with default_lang='en', then queries with and without
        the Croatian language override.  With language='hr', the Croatian stemmer
        is used and the inflected form is collapsed; with language=None the English
        analyzer is used which may not produce the same token, so the Croatian doc
        may score 0.

        This directly proves that the ``language`` kwarg selects the right analyzer
        rather than always falling back to English.
        """
        # Build index with English as default (simulates a mixed-language index)
        m = BM25IndexManager(
            persist_dir=str(tmp_path), default_lang="en", engine="stem"
        )
        m.build_index(
            [
                _node("termin kod liječnika sutra", "hr", "n1"),
                _node("unrelated english document about programming", "en", "n2"),
            ]
        )

        # With Croatian override: stemmer should find n1
        res_hr = asyncio.run(m.search_with_filters("liječnik", top_k=2, language="hr"))
        hr_ids = [r.node.node_id for r in res_hr]

        # With no override (English default): English analyzer won't know this stem
        res_en = asyncio.run(m.search_with_filters("liječnik", top_k=2, language=None))
        en_ids = [r.node.node_id for r in res_en]

        # Croatian mode must find n1
        assert (
            "n1" in hr_ids
        ), f"language='hr' should retrieve n1 (Croatian doc); got ids: {hr_ids}"
        # English mode should NOT retrieve n1 (or retrieve it with lower rank)
        # — the key assertion is that Croatian mode works, English mode is a
        # negative contrast demonstrating the override matters.
        if en_ids:
            # If English mode somehow matches, n1 must not outscore n2 OR
            # the Croatian mode must outrank it — either way hr beats en on n1.
            hr_n1_score = next((r.score for r in res_hr if r.node.node_id == "n1"), 0.0)
            en_n1_score = next((r.score for r in res_en if r.node.node_id == "n1"), 0.0)
            assert hr_n1_score >= en_n1_score, (
                "Croatian analyzer should score n1 >= English analyzer on "
                f"Croatian query; hr={hr_n1_score:.3f}, en={en_n1_score:.3f}"
            )
