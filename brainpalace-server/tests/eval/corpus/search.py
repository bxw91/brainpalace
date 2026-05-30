"""Hybrid search fusion."""


def reciprocal_rank_fusion(
    bm25_ranking: list[str], vector_ranking: list[str], k: int = 60
) -> list[str]:
    """Fuse a BM25 ranking and a vector ranking with Reciprocal Rank Fusion.

    Each document's fused score is the sum of 1 / (k + rank) across the two
    rankings. Documents are returned sorted by descending fused score. RRF is
    rank-based, so it is robust to the different score scales of BM25 and
    cosine similarity.
    """
    scores: dict[str, float] = {}
    for ranking in (bm25_ranking, vector_ranking):
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)
