"""Tests for BM25IndexManager multi-language support."""

import asyncio

from llama_index.core.schema import TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager


def _node(text, lang, sid):
    return TextNode(
        text=text, id_=sid, metadata={"text_language": lang, "source_type": "doc"}
    )


def test_croatian_query_matches_inflected_doc(tmp_path):
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="hr", engine="stem")
    m.build_index(
        [
            _node("termin kod liječnika sutra", "hr", "n1"),
            _node("nabava uredskog materijala", "hr", "n2"),
        ]
    )
    res = asyncio.run(m.search_with_filters("liječnik", top_k=1))
    assert res and res[0].node.node_id == "n1"


def test_scores_normalized_0_1(tmp_path):
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m.build_index(
        [_node("the quick brown fox", "en", "a"), _node("lazy dog sleeps", "en", "b")]
    )
    res = asyncio.run(m.search_with_filters("fox", top_k=2))
    assert res and 0.0 <= res[0].score <= 1.0


def test_persist_reload_keeps_croatian(tmp_path):
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="hr", engine="stem")
    m.build_index([_node("termin kod liječnika", "hr", "n1")])
    m.persist()
    m2 = BM25IndexManager(persist_dir=str(tmp_path))  # no lang passed → read config
    m2.initialize()
    res = asyncio.run(m2.search_with_filters("liječnika", top_k=1))
    assert res and res[0].node.node_id == "n1"


def test_empty_query_returns_empty(tmp_path):
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m.build_index([_node("hello world", "en", "a")])
    assert asyncio.run(m.search_with_filters("the and is", top_k=3)) == []


def test_empty_corpus_noop(tmp_path):
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m.build_index([])  # issue #143: no raise
    assert m.corpus_size == 0


def test_rebuild_from_corpus_with_all_stopword_doc(tmp_path):
    """rebuild_from_corpus must not crash when corpus contains only stopword docs.

    Regression test: bm25s.BM25.index([[],[],...]) raises
    ``ValueError: max() iterable argument is empty`` when every document in the
    index call produces an empty token list (empty vocabulary). build_index
    already guards this with an ``["__empty__"]`` placeholder; rebuild_from_corpus
    did not, so a corpus composed entirely of stopword-only docs crashed on the
    rebuild/migration path.
    """
    # Build a corpus whose every document contains only stopwords.
    # "the and is of" and "a an the" both tokenize to [] under English analysis.
    # build_index protects with __empty__, so this succeeds.
    m1 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m1.build_index(
        [
            _node("the and is of", "en", "sw1"),
            _node("a an the", "en", "sw2"),
        ]
    )
    assert m1.corpus_size == 2

    # Call rebuild_from_corpus() directly on a new manager that has already
    # loaded the stored corpus.  This isolates the bug without relying on the
    # fingerprint-mismatch path.
    m2 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="lemma")
    m2._bm25 = m1._bm25  # simulate "loaded from disk"
    m2._corpus = list(m1._corpus)
    m2.rebuild_from_corpus()  # must not raise ValueError

    assert m2.corpus_size == 2


def test_rebuild_from_corpus_real_doc_still_queryable(tmp_path):
    """After rebuild that includes an all-stopword doc, real docs remain searchable.

    Complements test_rebuild_from_corpus_with_all_stopword_doc by verifying that
    the __empty__ placeholder does not interfere with retrieval of normal docs.
    """
    m1 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m1.build_index(
        [
            _node("quick brown fox jumps", "en", "real"),
            _node("the and is of", "en", "stopwords"),
        ]
    )

    m2 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="lemma")
    m2._bm25 = m1._bm25
    m2._corpus = list(m1._corpus)
    m2.rebuild_from_corpus()

    res = asyncio.run(m2.search_with_filters("fox", top_k=1))
    assert res and res[0].node.node_id == "real"


def test_initialize_triggers_rebuild_on_engine_mismatch(tmp_path):
    """initialize() rebuilds the index when the persisted engine differs.

    Exercises the fingerprint-mismatch path THROUGH initialize() — the primary
    plan guarantee that a changed engine triggers a corpus re-tokenization.
    Asserts: (a) no exception raised, (b) a known doc is still queryable.
    """
    # Build and persist with "stem" engine.
    m1 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m1.build_index(
        [
            _node("quick brown fox jumps", "en", "doc1"),
            _node("lazy dog sleeps soundly", "en", "doc2"),
        ]
    )
    # Confirm the index is on disk.
    assert (tmp_path / "params.index.json").exists() or (
        tmp_path / "data.csc.index.npy"
    ).exists()

    # Create a NEW manager with a different engine over the same persist_dir.
    # initialize() must detect the mismatch and call rebuild_from_corpus().
    m2 = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="lemma")
    m2.initialize()  # must not raise

    # The rebuilt index must still answer queries.
    res = asyncio.run(m2.search_with_filters("fox", top_k=1))
    assert res, "Expected at least one result after engine-mismatch rebuild"
    assert res[0].node.node_id == "doc1"
