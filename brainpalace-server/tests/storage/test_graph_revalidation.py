"""Plan 3 Task 1 — purge→rewrite of an UNCHANGED file must keep its edges."""

import pytest

from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def mgr(tmp_path):
    m = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    m.initialize()
    return m


_KW = {
    "subject_id": "f.py:a",
    "object_id": "f.py:b",
    "subject_name": "a",
    "object_name": "b",
    "source_file": "f.py",
    "domain": "code",
}


def test_identical_readd_after_invalidate_reopens_edge(mgr):
    assert mgr.add_triplet("a", "calls", "b", **_KW) is True
    assert mgr.invalidate_by_source_file("f.py", domain="code") == 1
    # The dedup set must not block the rewrite...
    assert mgr.add_triplet("a", "calls", "b", **_KW) is True
    # ...and the store row must be re-opened (valid_until back to NULL).
    row = mgr._graph_store._conn.execute("SELECT valid_until FROM edges").fetchone()
    assert row["valid_until"] is None


class _Doc:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata

    def get_content(self):
        return self.text


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


def test_same_content_reindex_keeps_calls_edges(tmp_path):
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    index = GraphIndexManager(graph_store=mgr)
    src = "def helper():\n    pass\ndef top():\n    helper()\n"
    index.build_from_documents([_pyfile("m.py", src)])
    index.build_from_documents([_pyfile("m.py", src)])  # unchanged re-index
    rows = mgr._graph_store._conn.execute(
        "SELECT source_id, target_id FROM edges "
        "WHERE label = 'calls' AND valid_until IS NULL"
    ).fetchall()
    assert ("m.py:top", "m.py:helper") in {(r[0], r[1]) for r in rows}
    # And the nodes survived the orphan sweep.
    names = {r[0] for r in mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert {"m.py:top", "m.py:helper"} <= names
