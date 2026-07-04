"""Plan C Task 3 — manager wrappers guard + delegate the git-graph reads."""

from brainpalace_server.storage.graph_store import GraphStoreManager


def test_wrappers_delegate(tmp_path) -> None:
    # Canonical SQLite-backed manager fixture (same as
    # tests/storage/test_add_triplet_endpoint_domains.py).
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    assert mgr.add_triplet(
        "abc1234 subj",
        "modifies",
        "a.py",
        subject_type="Commit",
        object_type="File",
        subject_id="git-commit:abc1234",
        object_id="/repo/a.py",
        source_file="commit:abc1234",
        domain="git",
        subject_domain="git",
        object_domain="code",
    )
    assert mgr.existing_node_ids(["/repo/a.py", "nope"]) == {"/repo/a.py"}
    assert mgr.co_changed_files("/repo/a.py") == []  # single file: no partners


def test_wrappers_neutral_when_uninitialized(tmp_path) -> None:
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    assert mgr.existing_node_ids(["x"]) == set()
    assert mgr.co_changed_files("x") == []
