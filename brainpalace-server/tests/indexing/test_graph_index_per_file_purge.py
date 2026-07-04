import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


class _Doc:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata

    def get_content(self):
        return self.text


@pytest.fixture
def gi(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    return GraphIndexManager(graph_store=mgr), mgr


def _pyfile(path, src):
    return _Doc(
        src,
        {
            "source_type": "code",
            "language": "python",
            "file_path": path,
            "source": path,
        },
    )


def test_all_functions_become_nodes(gi):
    index, mgr = gi
    src = "def a():\n    pass\ndef b():\n    pass\n"
    index.build_from_documents([_pyfile("m.py", src)])
    names = {r[0] for r in mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert "m.py:a" in names and "m.py:b" in names


def test_reindex_purges_removed_symbol(gi):
    index, mgr = gi
    index.build_from_documents(
        [_pyfile("m.py", "def a():\n    pass\ndef b():\n    pass\n")]
    )
    # rename b -> c
    index.build_from_documents(
        [_pyfile("m.py", "def a():\n    pass\ndef c():\n    pass\n")]
    )
    ids = {r[0] for r in mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert "m.py:c" in ids
    assert "m.py:b" not in ids  # stale removed by purge + sweep
