from brainpalace_server.config.ranking_config import RankingConfig
from brainpalace_server.models.query import QueryResult
from brainpalace_server.services.query_service import QueryService


def _r(source_type, score, authority=None):
    metadata = {}
    if authority is not None:
        metadata["authority"] = authority
    return QueryResult(
        text=source_type,
        source=f"{source_type}.x",
        score=score,
        chunk_id=f"{source_type}-{score}-{authority}",
        source_type=source_type,
        metadata=metadata,
    )


def test_none_config_is_noop():
    qs = QueryService(ranking_config=None)
    rs = [_r("doc", 0.9), _r("code", 0.8)]
    out = qs._apply_source_weights(list(rs))
    assert [(r.source_type, r.score) for r in out] == [("doc", 0.9), ("code", 0.8)]


def test_default_half_weight_reranks_mixed():
    qs = QueryService(ranking_config=RankingConfig())  # doc_weight=0.5
    out = qs._apply_source_weights([_r("doc", 0.8), _r("code", 0.6)])
    # doc 0.8*0.5=0.4 < code 0.6 ⇒ code first, doc still present
    assert [r.source_type for r in out] == ["code", "doc"]
    assert any(r.source_type == "doc" for r in out)


def test_homogeneous_corpus_order_unchanged():
    qs = QueryService(ranking_config=RankingConfig())  # doc_weight=0.5
    out = qs._apply_source_weights([_r("doc", 0.9), _r("doc", 0.7), _r("doc", 0.5)])
    assert [round(r.score, 3) for r in out] == [0.45, 0.35, 0.25]  # same order


def test_doc_weight_one_is_neutral():
    qs = QueryService(ranking_config=RankingConfig(doc_weight=1.0))
    out = qs._apply_source_weights([_r("doc", 0.9), _r("code", 0.8)])
    assert [(r.source_type, r.score) for r in out] == [("doc", 0.9), ("code", 0.8)]


def test_weight_zero_hard_drops_docs():
    qs = QueryService(ranking_config=RankingConfig(doc_weight=0.0))
    out = qs._apply_source_weights([_r("doc", 0.9), _r("code", 0.3)])
    assert [r.source_type for r in out] == ["code"]  # docs dropped, still indexed


# ---------------------------------------------------------------------------
# reference_rank_penalty (6.5 B): authority-aware soft ranking
# ---------------------------------------------------------------------------


def test_reference_authority_penalized():
    """A reference-authority result is soft-penalized and re-sorted below an
    equal-score authoritative result. source_type='code' isolates the
    authority penalty from doc_weight."""
    qs = QueryService(ranking_config=RankingConfig(reference_rank_penalty=0.5))
    out = qs._apply_source_weights(
        [_r("code", 0.8, authority="reference"), _r("code", 0.8)]
    )
    # reference 0.8*0.5=0.4 < authoritative 0.8 ⇒ authoritative first
    assert out[0].metadata.get("authority") is None
    assert out[1].metadata.get("authority") == "reference"
    assert round(out[1].score, 3) == 0.4


def test_penalty_zero_drops_reference_results():
    qs = QueryService(ranking_config=RankingConfig(reference_rank_penalty=0.0))
    out = qs._apply_source_weights(
        [_r("code", 0.9, authority="reference"), _r("code", 0.3)]
    )
    # reference hard-dropped (still indexed); authoritative kept
    assert [r.metadata.get("authority") for r in out] == [None]


def test_missing_authority_means_no_penalty():
    qs = QueryService(ranking_config=RankingConfig(reference_rank_penalty=0.5))
    out = qs._apply_source_weights([_r("code", 0.9), _r("code", 0.7)])
    # no authority key on either ⇒ untouched, order preserved
    assert [round(r.score, 3) for r in out] == [0.9, 0.7]
