"""Plan C Task 2 — existence lookup + computed co-change view."""

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


class _N:
    def __init__(self, id, name, label, domain):
        self.id, self.name, self.label = id, name, label
        self.properties: dict = {}
        self.domain = domain


class _R:
    def __init__(self, source_id, label, target_id):
        self.source_id, self.label, self.target_id = source_id, label, target_id
        self.properties: dict = {}


def _seed(store: SQLitePropertyGraphStore) -> None:
    files = [f"/repo/{n}.py" for n in "abc"]
    store.upsert_nodes(
        [_N(f, f.rsplit("/", 1)[-1], "File", "code") for f in files]
        + [_N(f"git-commit:s{i}", f"s{i} subj", "Commit", "git") for i in (1, 2, 3)]
    )
    # s1 touches a+b; s2 touches a+b; s3 touches a+c  → co-change(a): b=2, c=1
    pairs = [
        ("s1", "a"),
        ("s1", "b"),
        ("s2", "a"),
        ("s2", "b"),
        ("s3", "a"),
        ("s3", "c"),
    ]
    store.upsert_relations(
        [_R(f"git-commit:{s}", "modifies", f"/repo/{f}.py") for s, f in pairs]
    )


def test_existing_node_ids() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    _seed(store)
    got = store.existing_node_ids(["/repo/a.py", "/repo/zzz.py", "git-commit:s1"])
    assert got == {"/repo/a.py", "git-commit:s1"}
    assert store.existing_node_ids([]) == set()


def test_co_changed_files_threshold_and_order() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    _seed(store)
    out = store.co_changed_files("/repo/a.py", min_shared=2)
    assert out == [{"file_id": "/repo/b.py", "name": "b.py", "shared_commits": 2}]
    out1 = store.co_changed_files("/repo/a.py", min_shared=1)
    assert [o["file_id"] for o in out1] == ["/repo/b.py", "/repo/c.py"]


def test_co_change_ignores_invalidated_edges() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    _seed(store)
    # History rewrite: close s2's edges → b drops to 1 shared commit.
    store._conn.execute(
        "UPDATE edges SET valid_until = '2026-01-01T00:00:00+00:00' "
        "WHERE source_id = 'git-commit:s2'"
    )
    store._conn.commit()
    assert store.co_changed_files("/repo/a.py", min_shared=2) == []
