"""BM25 incremental add/remove for text ingest (spec Item 3).

No incremental tokenizer exists in bm25s, so add/remove mutate the corpus
and delegate to rebuild_from_corpus (re-tokenize only, no re-embed)."""

from brainpalace_server.indexing.bm25_index import BM25IndexManager


def _mgr(tmp_path):
    return BM25IndexManager(persist_dir=str(tmp_path))


def test_add_chunks_makes_text_searchable(tmp_path):
    m = _mgr(tmp_path)
    m.add_chunks(
        [
            {
                "node_id": "ing_1",
                "text": "racun za struju iznos 420 kuna",
                "metadata": {"source_type": "ingest", "source_id": "s1"},
            }
        ]
    )
    assert m.corpus_size == 1
    assert m.is_initialized


def test_add_chunks_same_id_replaces(tmp_path):
    m = _mgr(tmp_path)
    m.add_chunks([{"node_id": "ing_1", "text": "stari", "metadata": {}}])
    m.add_chunks([{"node_id": "ing_1", "text": "novi", "metadata": {}}])
    assert m.corpus_size == 1


def test_remove_chunks(tmp_path):
    m = _mgr(tmp_path)
    m.add_chunks([{"node_id": "ing_1", "text": "x y z", "metadata": {}}])
    m.remove_chunks(["ing_1"])
    assert m.corpus_size == 0
