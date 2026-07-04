"""Plan D Task 3 — per-file builds persist SymbolDef positions on nodes."""

from brainpalace_server.indexing.chunking import ChunkMetadata, TextChunk
from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager

SRC = """\
class Greeter:
    def hello(self) -> str:
        return "hi"
"""


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
        token_count=1,
        metadata=md,
    )


def test_positions_written_for_symbols(tmp_path) -> None:
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    gim = GraphIndexManager(graph_store=mgr)
    path = f"{tmp_path}/pkg/g.py".replace("\\", "/")
    gim.build_from_documents([_chunk(path, SRC)], root=str(tmp_path))

    cls = mgr.get_node(f"{path}:Greeter")
    meth = mgr.get_node(f"{path}:Greeter.hello")
    assert cls is not None and meth is not None
    assert cls["properties"]["path"] == path
    assert cls["properties"]["line"] == 0
    assert meth["properties"]["line"] == 1
    assert isinstance(meth["properties"]["character"], int)
