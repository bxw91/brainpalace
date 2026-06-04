"""Migration tests: legacy LlamaIndex BM25 corpus shape → multi-language manager.

An existing deployment that upgraded from the old LlamaIndex ``BM25Retriever``
has an on-disk bm25s index whose corpus payloads were written by LlamaIndex as
``node_to_metadata_dict(node) | {"node_id": node.node_id}`` — i.e. keys like
``_node_content``, ``_node_type``, ``doc_id``, ``document_id``, ``node_id`` with
NO top-level ``"text"`` and NO top-level ``"metadata"``.

The new ``BM25IndexManager`` must migrate this shape on first start (no
``analyzer_config.json`` present) without crashing, re-persist it in the new
shape, and still retrieve.

NOTE: this test intentionally does NOT import ``llama_index.retrievers.bm25``
(that package is being removed). The legacy payload is reproduced via
``llama_index.core`` only, mirroring exactly what the old retriever's
``persist()`` wrote.
"""

import asyncio

import bm25s
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.utils import node_to_metadata_dict

from brainpalace_server.indexing.bm25_index import BM25IndexManager


def _legacy_corpus_payload(node: TextNode) -> dict:
    """Reproduce the exact corpus entry old LlamaIndex BM25Retriever persisted.

    Source: llama_index/retrievers/bm25/base.py ->
        self.corpus = [node_to_metadata_dict(node) | {"node_id": node.node_id} ...]
    """
    return node_to_metadata_dict(node) | {"node_id": node.node_id}


def _write_legacy_index(persist_dir, nodes, token_lists):
    """Persist a bm25s index with legacy-shaped corpus and NO analyzer_config."""
    legacy_corpus = [_legacy_corpus_payload(n) for n in nodes]
    bm = bm25s.BM25(corpus=legacy_corpus)
    bm.index(token_lists)
    bm.save(str(persist_dir), corpus=legacy_corpus)
    # Deliberately do NOT write analyzer_config.json -> this is the legacy
    # "no-config" condition that triggers the rebuild branch.


def test_legacy_corpus_payload_has_no_top_level_text_or_metadata():
    """Guard: the legacy payload really lacks the new-shape keys."""
    payload = _legacy_corpus_payload(
        TextNode(text="termin kod liječnika", id_="n1", metadata={"source_type": "doc"})
    )
    assert "text" not in payload
    assert "metadata" not in payload
    assert "_node_content" in payload
    assert payload["node_id"] == "n1"


def test_migrates_legacy_llamaindex_corpus_without_crashing(tmp_path):
    nodes = [
        TextNode(
            text="termin kod liječnika", id_="n1", metadata={"source_type": "doc"}
        ),
        TextNode(
            text="nabava uredskog materijala", id_="n2", metadata={"source_type": "doc"}
        ),
    ]
    _write_legacy_index(
        tmp_path,
        nodes,
        [["termin", "liječnik"], ["nabava", "materijal"]],
    )

    # New manager over the legacy persist dir. initialize() must NOT raise and
    # must migrate the legacy corpus shape.
    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="hr", engine="stem")
    m.initialize()  # must not raise KeyError

    assert m.is_initialized
    res = asyncio.run(m.search_with_filters("liječnik", top_k=1))
    assert res and res[0].node.node_id == "n1"


def test_migration_repersists_new_shape_corpus(tmp_path):
    """After migration the corpus is re-saved in NEW shape + analyzer_config written,
    so a second start is the fast no-remigrate path."""
    nodes = [
        TextNode(
            text="termin kod liječnika", id_="n1", metadata={"source_type": "doc"}
        ),
    ]
    _write_legacy_index(tmp_path, nodes, [["termin", "liječnik"]])

    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="hr", engine="stem")
    m.initialize()

    # analyzer_config.json now exists.
    cfg_path = tmp_path / "analyzer_config.json"
    assert cfg_path.exists()

    # The re-persisted corpus is new-shape: top-level "text" + "metadata".
    reloaded = bm25s.BM25.load(str(tmp_path), load_corpus=True)
    entry = list(reloaded.corpus)[0]
    assert "text" in entry
    assert "metadata" in entry
    assert "node_id" in entry

    # A fresh manager over the migrated dir loads via the fast path and still
    # answers queries.
    m2 = BM25IndexManager(persist_dir=str(tmp_path))
    m2.initialize()
    res = asyncio.run(m2.search_with_filters("liječnik", top_k=1))
    assert res and res[0].node.node_id == "n1"


def test_unreadable_legacy_corpus_degrades_gracefully(tmp_path, caplog):
    """A genuinely unreadable legacy corpus must not crash startup.

    We write index files but a corpus payload that is missing BOTH the new-shape
    keys AND the legacy ``_node_content`` -> reconstruction is impossible. The
    manager should log an actionable message and leave _bm25 = None rather than
    raising on initialize()."""
    broken_corpus = [{"node_id": "x", "garbage": True}]
    bm = bm25s.BM25(corpus=broken_corpus)
    bm.index([["foo"]])
    bm.save(str(tmp_path), corpus=broken_corpus)

    m = BM25IndexManager(persist_dir=str(tmp_path), default_lang="en", engine="stem")
    m.initialize()  # must not raise

    assert m._bm25 is None
