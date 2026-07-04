"""Plan 4 Task 5 — exact-graph edges must map to a chunk for --mode graph."""

import json

import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Doc:
    def __init__(self, text, metadata, chunk_id):
        self.text = text
        self.metadata = metadata
        self.chunk_id = chunk_id

    def get_content(self):
        return self.text


@pytest.fixture
def gi(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    return GraphIndexManager(graph_store=mgr), mgr


def test_code_edges_carry_source_chunk_id(gi):
    index, mgr = gi
    doc = _Doc(
        "def a():\n    pass\n",
        {
            "source_type": "code",
            "language": "python",
            "file_path": "m.py",
            "source": "m.py",
        },
        chunk_id="chunk_42",
    )
    index.build_from_documents([doc])
    rows = mgr._graph_store._conn.execute(
        "SELECT properties FROM edges WHERE valid_until IS NULL"
    ).fetchall()
    assert rows
    assert all(json.loads(r[0]).get("source_chunk_id") == "chunk_42" for r in rows)
