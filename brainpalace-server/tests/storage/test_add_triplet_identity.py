import pytest

from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def mgr(tmp_path):
    m = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    m.initialize()
    return m


def test_node_id_is_canonical_name_is_short(mgr):
    mgr.add_triplet(
        subject="foo",
        predicate="contains",
        obj="bar",
        subject_id="f.py:foo",
        object_id="f.py:bar",
        subject_name="foo",
        object_name="bar",
        subject_type="Module",
        object_type="Function",
        source_file="f.py",
    )
    store = mgr._graph_store
    rows = {r[0]: r[1] for r in store._conn.execute("SELECT id, name FROM nodes")}
    assert "f.py:foo" in rows and rows["f.py:foo"] == "foo"
    assert "f.py:bar" in rows and rows["f.py:bar"] == "bar"
    sf = store._conn.execute("SELECT source_file FROM edges").fetchone()[0]
    assert sf == "f.py"
