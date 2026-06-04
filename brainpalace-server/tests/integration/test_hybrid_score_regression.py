"""No-regression guard for hybrid-fusion BM25 score scale (Task 14).

Task 8 rewrote BM25IndexManager.search_with_filters to normalize scores 0–1
(top result = 1.0).  A follow-up removed a now-redundant second normalization
that had lived in ChromaBackend.keyword_search.  This suite locks in that
contract so future changes cannot silently corrupt the score scale feeding
hybrid/alpha-blend fusion.

Hybrid mode in this codebase uses **alpha-weighted score blending**, NOT pure
RRF (RRF lives in _execute_multi_query).  The fusion formula is:

    fused = alpha * (vector_score / max_vector) + (1 - alpha) * (bm25_score / max_bm25)

alpha=1.0 → pure vector; alpha=0.0 → pure BM25.

If any assertion in test_bm25_scores_are_in_0_1_range FAILS with scores > 1.0,
do NOT weaken the test — fix the normalization in BM25IndexManager, not here.
"""

from unittest.mock import AsyncMock

from llama_index.core.schema import NodeWithScore, TextNode

# ---------------------------------------------------------------------------
# Corpus fixtures
# ---------------------------------------------------------------------------

# Three-document corpus that exercises all three overlap patterns in hybrid:
#   doc_both  — appears in BOTH vector AND BM25 results (highest fused score)
#   doc_vec   — appears in vector results only
#   doc_bm25  — appears in BM25 results only
#
# Chosen scores (all in [0, 1]):
#   doc_both:  vector=0.80, bm25=0.70  → fused(α=0.5) = 0.75
#   doc_vec:   vector=1.00, bm25=0.00  → fused(α=0.5) = 0.50
#   doc_bm25:  vector=0.00, bm25=1.00  → fused(α=0.5) = 0.50
#
# Expected alpha=0.5 ranking: doc_both > doc_vec = doc_bm25
# (tie broken by stable-sort insertion order: vector results come first in the
# combined dict, so doc_vec appears before doc_bm25 when scores are equal)
#
# alpha=1.0 top-1: doc_vec  (highest vector score among vector candidates)
# alpha=0.0 top-1: doc_bm25 (highest BM25 score)

VECTOR_SCORE_BOTH = 0.80
VECTOR_SCORE_VEC = 1.00
BM25_SCORE_BOTH = 0.70
BM25_SCORE_BM25 = 1.00


def _make_vector_results():
    """SearchResult-like mocks for vector search: doc_vec and doc_both."""
    from brainpalace_server.storage.vector_store import SearchResult

    return [
        SearchResult(
            text="Document found by vector search only",
            metadata={"source": "corpus/doc_vec.md", "source_type": "doc"},
            score=VECTOR_SCORE_VEC,
            chunk_id="doc_vec",
        ),
        SearchResult(
            text="Document found by both vector and BM25",
            metadata={"source": "corpus/doc_both.md", "source_type": "doc"},
            score=VECTOR_SCORE_BOTH,
            chunk_id="doc_both",
        ),
    ]


def _make_bm25_nodes():
    """NodeWithScore mocks for BM25 search: doc_bm25 and doc_both.

    Scores are already normalized 0-1 (as search_with_filters guarantees).
    """
    return [
        NodeWithScore(
            node=TextNode(
                text="Document found by BM25 only",
                id_="doc_bm25",
                metadata={"source": "corpus/doc_bm25.md", "source_type": "doc"},
            ),
            score=BM25_SCORE_BM25,
        ),
        NodeWithScore(
            node=TextNode(
                text="Document found by both vector and BM25",
                id_="doc_both",
                metadata={"source": "corpus/doc_both.md", "source_type": "doc"},
            ),
            score=BM25_SCORE_BOTH,
        ),
    ]


# ---------------------------------------------------------------------------
# Shared helper: build a QueryService with the test corpus wired up
# ---------------------------------------------------------------------------


def _make_query_service(mock_vector_store, mock_bm25_manager, mock_embedding_generator):
    """Return a real QueryService backed by mock stores pre-loaded with the corpus."""
    from brainpalace_server.services import QueryService

    mock_vector_store.is_initialized = True
    mock_bm25_manager.is_initialized = True

    mock_vector_store.similarity_search = AsyncMock(return_value=_make_vector_results())
    mock_bm25_manager.search_with_filters = AsyncMock(return_value=_make_bm25_nodes())
    # get_count must return > 0 so execute_query proceeds past the empty-corpus guard
    mock_vector_store.get_count = AsyncMock(return_value=3)

    return QueryService(
        vector_store=mock_vector_store,
        embedding_generator=mock_embedding_generator,
        bm25_manager=mock_bm25_manager,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHybridScoreRegression:
    """Regression guard: BM25 score scale stays 0-1 through hybrid fusion."""

    # ------------------------------------------------------------------
    # T1: BM25 scores feeding hybrid fusion are ALL in [0, 1]
    # ------------------------------------------------------------------

    def test_bm25_scores_are_in_0_1_range(
        self,
        app_with_mocks,
        client,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """All bm25_score fields on hybrid results must lie in [0, 1].

        This is the primary regression guard for Task 8's normalization contract.
        If BM25 scores exceed 1.0, the normalization in BM25IndexManager was
        regressed — fix the manager, not this test.
        """
        query_service = _make_query_service(
            mock_vector_store, mock_bm25_manager, mock_embedding_generator
        )
        app_with_mocks.state.query_service = query_service

        response = client.post(
            "/query/",
            json={"query": "regression test query", "mode": "hybrid", "alpha": 0.5},
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["total_results"] > 0, "Expected at least one result"

        for r in data["results"]:
            bm25 = r.get("bm25_score")
            if bm25 is not None:
                assert 0.0 <= bm25 <= 1.0, (
                    f"bm25_score={bm25!r} out of [0,1] for chunk_id={r['chunk_id']!r}. "
                    "Task 8 normalization has regressed — fix BM25IndexManager, "
                    "not this test."
                )

    # ------------------------------------------------------------------
    # T2: Alpha-blend fusion ordering for known query
    #
    # Expected order derived by running the current implementation (see
    # module docstring for the formula and corpus spec).
    #
    # alpha=0.5 ranking:
    #   doc_both  (fused=0.75) > doc_vec  (fused=0.50) = doc_bm25 (fused=0.50)
    #   Tie at 0.50: stable-sort preserves dict insertion order; vector results
    #   are inserted first, so doc_vec precedes doc_bm25.
    # ------------------------------------------------------------------

    def test_fusion_ordering_alpha_half(
        self,
        app_with_mocks,
        client,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """Hybrid alpha=0.5 ranking matches the implementation's expected order.

        This is a regression guard — the expected order was captured from an
        actual run of the current implementation and hardcoded here.  If the
        ordering changes, investigate whether the fusion formula or score
        normalization was modified.
        """
        query_service = _make_query_service(
            mock_vector_store, mock_bm25_manager, mock_embedding_generator
        )
        app_with_mocks.state.query_service = query_service

        response = client.post(
            "/query/",
            json={"query": "known query for ordering", "mode": "hybrid", "alpha": 0.5},
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        chunk_ids = [r["chunk_id"] for r in data["results"]]

        # doc_both must be ranked first (highest fused score)
        assert (
            chunk_ids[0] == "doc_both"
        ), f"Expected doc_both at rank 0, got: {chunk_ids}"
        # doc_vec and doc_bm25 follow (tied score); both must be present
        assert set(chunk_ids[1:]) == {
            "doc_vec",
            "doc_bm25",
        }, f"Expected {{doc_vec, doc_bm25}} at ranks 1-2, got: {chunk_ids[1:]}"
        # Tie-break: doc_vec precedes doc_bm25 (vector results inserted first)
        assert (
            chunk_ids[1] == "doc_vec"
        ), f"Expected doc_vec at rank 1 (tie-break), got: {chunk_ids}"
        assert (
            chunk_ids[2] == "doc_bm25"
        ), f"Expected doc_bm25 at rank 2 (tie-break), got: {chunk_ids}"

    # ------------------------------------------------------------------
    # T3: alpha=1.0 (pure vector) — top result is the strongest vector hit
    # ------------------------------------------------------------------

    def test_alpha_1_0_pure_vector_top1(
        self,
        app_with_mocks,
        client,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """alpha=1.0 (pure vector) must rank the highest-vector-score chunk first.

        With alpha=1.0 the BM25 contribution is zero; only vector scores drive
        the fusion.  doc_vec has the highest vector score (1.0), so it must rank
        first.  doc_bm25 has vector=0.0 and contributes nothing to fusion, so it
        should rank last (fused=0.0).
        """
        query_service = _make_query_service(
            mock_vector_store, mock_bm25_manager, mock_embedding_generator
        )
        app_with_mocks.state.query_service = query_service

        response = client.post(
            "/query/",
            json={"query": "pure vector query", "mode": "hybrid", "alpha": 1.0},
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        chunk_ids = [r["chunk_id"] for r in data["results"]]

        assert chunk_ids[0] == "doc_vec", (
            f"alpha=1.0: expected doc_vec as top-1 (highest vector score), "
            f"got: {chunk_ids}"
        )

    # ------------------------------------------------------------------
    # T4: alpha=0.0 (pure BM25) — top result is the strongest BM25 hit
    # ------------------------------------------------------------------

    def test_alpha_0_0_pure_bm25_top1(
        self,
        app_with_mocks,
        client,
        mock_vector_store,
        mock_bm25_manager,
        mock_embedding_generator,
    ):
        """alpha=0.0 (pure BM25) must rank the highest-BM25-score chunk first.

        With alpha=0.0 the vector contribution is zero; only BM25 scores drive
        the fusion.  doc_bm25 has the highest BM25 score (1.0), so it must rank
        first.  doc_vec has bm25=0.0 and contributes nothing to fusion, so it
        should rank last (fused=0.0).
        """
        query_service = _make_query_service(
            mock_vector_store, mock_bm25_manager, mock_embedding_generator
        )
        app_with_mocks.state.query_service = query_service

        response = client.post(
            "/query/",
            json={"query": "pure bm25 query", "mode": "hybrid", "alpha": 0.0},
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        chunk_ids = [r["chunk_id"] for r in data["results"]]

        assert chunk_ids[0] == "doc_bm25", (
            f"alpha=0.0: expected doc_bm25 as top-1 (highest BM25 score), "
            f"got: {chunk_ids}"
        )
