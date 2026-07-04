"""Plan 4 Task 1 — the per-file build must accept real ChunkMetadata chunks."""

import pytest

from brainpalace_server.indexing.chunking import ChunkMetadata, TextChunk
from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


def _chunk(path: str, text: str) -> TextChunk:
    md = ChunkMetadata(
        chunk_id="c1",
        source=path,
        file_name=path.rsplit("/", 1)[-1],
        chunk_index=0,
        total_chunks=1,
        source_type="code",
        language="python",
    )
    return TextChunk(
        chunk_id="c1",
        text=text,
        source=path,
        chunk_index=0,
        total_chunks=1,
        token_count=5,
        metadata=md,
    )


@pytest.fixture
def gi(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    return GraphIndexManager(graph_store=mgr), mgr


def test_build_accepts_dataclass_chunk_metadata(gi):
    index, mgr = gi
    n = index.build_from_documents([_chunk("/abs/pkg/m.py", "def a():\n    pass\n")])
    assert n > 0  # must not raise, must extract
    ids = {r[0] for r in mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert "/abs/pkg/m.py:a" in ids  # canonical id from the per-file pass
