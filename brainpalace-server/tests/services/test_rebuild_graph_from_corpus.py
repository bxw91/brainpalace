"""Plan 4 Task 6 — corpus rebuild adopts canonical identity + marks the flag."""

import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.services.indexing_service import IndexingService
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Node:
    def __init__(self, chunk_id, text, metadata):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata

    def get_content(self):
        return self.text


class _FakeBM25:
    is_initialized = True

    def __init__(self, nodes):
        self._nodes = nodes

    def initialize(self):
        pass

    def all_nodes(self):
        return self._nodes


@pytest.mark.asyncio
async def test_rebuild_from_corpus_marks_flag(tmp_path):
    store_mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    store_mgr.initialize()
    gim = GraphIndexManager(graph_store=store_mgr)
    nodes = [
        _Node(
            "c1",
            "def a():\n    pass\n",
            {
                "source_type": "code",
                "language": "python",
                "file_path": "m.py",
                "source": "m.py",
            },
        )
    ]
    svc = IndexingService.__new__(IndexingService)  # method-scoped unit test
    svc.bm25_manager = _FakeBM25(nodes)
    svc.graph_index_manager = gim

    assert store_mgr.needs_code_identity_rebuild() is True
    n = await svc.rebuild_graph_from_corpus(str(tmp_path))
    assert n > 0
    assert store_mgr.needs_code_identity_rebuild() is False
    ids = {r[0] for r in store_mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert "m.py:a" in ids


@pytest.mark.asyncio
async def test_rebuild_empty_corpus_is_noop(tmp_path):
    store_mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    store_mgr.initialize()
    svc = IndexingService.__new__(IndexingService)
    svc.bm25_manager = _FakeBM25([])
    svc.graph_index_manager = GraphIndexManager(graph_store=store_mgr)
    assert await svc.rebuild_graph_from_corpus(None) == 0
    # Nothing to rebuild from — the flag stays pending for a later run.
    assert store_mgr.needs_code_identity_rebuild() is True
