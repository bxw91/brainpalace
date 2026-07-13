from llama_index.core.schema import TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager
from brainpalace_server.rehome.swap import swap_chunk_metadata


def _mk(tmp_path):
    idx = BM25IndexManager(persist_dir=str(tmp_path))
    nodes = [
        TextNode(text="hello world", id_="c1", metadata={"source": "/old/root/a.py"}),
        TextNode(text="ext doc", id_="c2", metadata={"source": "/somewhere/else/b.md"}),
    ]
    idx.build_index(nodes)
    idx.persist()
    return idx


def test_bm25_rehome_swaps_in_root_source_only(tmp_path):
    idx = _mk(tmp_path)
    changed = idx.rehome(lambda md: swap_chunk_metadata(md, "/old/root", "/new/home"))
    assert changed == 1  # only c1 was in-root

    sources = {
        idx._entry_to_fields(e)[0]: idx._entry_to_fields(e)[2].get("source")
        for e in (idx._corpus or [])
    }
    assert sources["c1"] == "/new/home/a.py"
    assert sources["c2"] == "/somewhere/else/b.md"
    # re-tokenize succeeded -> index usable again
    assert idx.is_initialized


def test_bm25_rehome_empty_corpus_noop(tmp_path):
    idx = BM25IndexManager(persist_dir=str(tmp_path))
    assert idx.rehome(lambda md: md) == 0
