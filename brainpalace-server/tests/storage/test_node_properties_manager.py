"""Plan D Task 2 — manager wrappers guard + delegate node-properties API."""

from brainpalace_server.storage.graph_store import GraphStoreManager


def _manager_with_sqlite(tmp_path) -> GraphStoreManager:
    # Canonical SQLite-backed manager fixture (same as
    # tests/storage/test_add_triplet_endpoint_domains.py).
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    return mgr


def test_wrappers_delegate(tmp_path) -> None:
    mgr = _manager_with_sqlite(tmp_path)
    assert mgr.add_triplet(
        "foo",
        "defined_in",
        "f.py",
        subject_type="Function",
        object_type="File",
        subject_id="f.py:foo",
        object_id="f.py",
        source_file="f.py",
    )
    assert mgr.set_node_properties({"f.py:foo": {"line": 3}}) == 1
    node = mgr.get_node("f.py:foo")
    assert node is not None and node["properties"] == {"line": 3}


def test_wrappers_neutral_when_uninitialized(tmp_path) -> None:
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    assert mgr.set_node_properties({"x": {"a": 1}}) == 0
    assert mgr.get_node("x") is None
