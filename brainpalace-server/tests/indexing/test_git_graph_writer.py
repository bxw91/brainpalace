"""Plan C Task 5 — writer hook: purge-before-write, per-endpoint domains,
no phantom Files, no git orphan sweep."""

from datetime import datetime, timezone

from brainpalace_server.indexing.git_graph import write_commit_graph
from brainpalace_server.indexing.git_loader import CommitRecord
from brainpalace_server.storage.graph_store import GraphStoreManager


def _rec(sha: str, files: list[str]) -> CommitRecord:
    return CommitRecord(
        sha=sha,
        author="Ada L",
        author_email="ada@example.com",
        committed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        subject=f"subj {sha}",
        body="",
        files_changed=files,
    )


def _mgr(tmp_path, monkeypatch) -> GraphStoreManager:
    # Canonical SQLite-backed manager (as in test_add_triplet_endpoint_domains).
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    # git_graph resolves the manager through its module-level accessor import:
    import brainpalace_server.indexing.git_graph as gg

    monkeypatch.setattr(gg, "get_graph_store_manager", lambda: mgr)
    return mgr


def test_writes_edges_onto_existing_file_nodes(tmp_path, monkeypatch) -> None:
    mgr = _mgr(tmp_path, monkeypatch)
    # Pre-existing canonical code File node (as the code build creates it).
    mgr.add_triplet(
        "a.py",
        "contains",
        "foo",
        subject_type="File",
        object_type="Function",
        subject_id="/repo/a.py",
        object_id="/repo/a.py:foo",
        source_file="/repo/a.py",
    )
    n = write_commit_graph([_rec("s1", ["a.py", "gone.py"])], "/repo")
    assert n == 2  # authored_by + one modifies (gone.py skipped)

    store = mgr._graph_store
    file_node = store.get_node("/repo/a.py") if hasattr(store, "get_node") else None
    if file_node is not None:  # Plan D landed: assert the domain didn't flip
        assert file_node["domain"] == "code"
    row = store._conn.execute(
        "SELECT count(*) FROM nodes WHERE domain = 'git'"
    ).fetchone()
    assert row[0] == 2  # Commit + Author only — no phantom File for gone.py


def test_rewrite_purges_then_rewrites(tmp_path, monkeypatch) -> None:
    mgr = _mgr(tmp_path, monkeypatch)
    mgr.add_triplet(
        "a.py",
        "contains",
        "foo",
        subject_type="File",
        object_type="Function",
        subject_id="/repo/a.py",
        object_id="/repo/a.py:foo",
        source_file="/repo/a.py",
    )
    write_commit_graph([_rec("s1", ["a.py"])], "/repo")
    # Same sha re-indexed (amend/rebase replay): old edges close, new open —
    # active edge count for the commit stays stable.
    write_commit_graph([_rec("s1", ["a.py"])], "/repo")
    store = mgr._graph_store
    active = store._conn.execute(
        "SELECT count(*) FROM edges WHERE source_id = 'git-commit:s1' "
        "AND valid_until IS NULL"
    ).fetchone()[0]
    assert active == 2


def test_disabled_graph_is_noop(tmp_path, monkeypatch) -> None:
    _mgr(tmp_path, monkeypatch)
    from brainpalace_server.config import settings

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", False)
    assert write_commit_graph([_rec("s1", ["a.py"])], "/repo") == 0
