"""Plan E — shortest-path search on the SQLite graph store."""

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


class _N:
    def __init__(self, id, name, label="Entity", domain="code"):
        self.id = id
        self.name = name
        self.label = label
        self.properties = {}
        self.domain = domain


class _R:
    def __init__(self, source_id, target_id, label):
        self.source_id = source_id
        self.target_id = target_id
        self.label = label
        self.properties = {}


def _store_with_chain():
    s = SQLitePropertyGraphStore(":memory:")
    s.upsert_nodes(
        [
            _N("a", "a.py", "File"),
            _N("b", "b.py", "File"),
            _N("c", "c.py", "File"),
            _N("d", "d.py", "File"),
            _N("g", "deadbeef fix", "Commit", domain="git"),
        ]
    )
    s.upsert_relations(
        [
            _R("a", "b", "imports"),
            _R("b", "c", "imports"),
            _R("d", "c", "imports"),
            _R("g", "a", "modifies"),
        ]
    )
    return s


def test_direct_edge_is_length_one():
    s = _store_with_chain()
    out = s.find_paths("a", "b")
    assert len(out["paths"]) == 1
    p = out["paths"][0]
    assert p["node_ids"] == ["a", "b"]
    assert p["length"] == 1
    assert p["edges"][0] == {"source": "a", "target": "b", "label": "imports"}
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"a", "b"}


def test_undirected_traversal_records_stored_direction():
    # a→b→c and d→c: path a..d must walk c→d against the d→c edge.
    s = _store_with_chain()
    out = s.find_paths("a", "d")
    assert out["paths"][0]["node_ids"] == ["a", "b", "c", "d"]
    last = out["paths"][0]["edges"][-1]
    assert last == {"source": "d", "target": "c", "label": "imports"}


def test_max_depth_bounds_search():
    s = _store_with_chain()
    assert s.find_paths("a", "d", max_depth=2)["paths"] == []


def test_same_node_is_trivial_path():
    s = _store_with_chain()
    out = s.find_paths("a", "a")
    assert out["paths"] == [{"node_ids": ["a"], "edges": [], "length": 0}]


def test_unknown_endpoint_is_empty():
    s = _store_with_chain()
    assert s.find_paths("a", "zzz")["paths"] == []


def test_domains_filter_excludes_git_hop():
    s = _store_with_chain()
    # Without filter, g reaches b through a.
    assert s.find_paths("g", "b")["paths"] != []
    # code-only filter drops the git-endpoint edge.
    assert s.find_paths("g", "b", domains=["code"])["paths"] == []


def test_multiple_shortest_paths_capped_by_limit():
    s = SQLitePropertyGraphStore(":memory:")
    s.upsert_nodes([_N(x, x) for x in ("s", "m1", "m2", "t")])
    s.upsert_relations(
        [
            _R("s", "m1", "calls"),
            _R("m1", "t", "calls"),
            _R("s", "m2", "calls"),
            _R("m2", "t", "calls"),
        ]
    )
    out = s.find_paths("s", "t")
    assert len(out["paths"]) == 2
    assert {tuple(p["node_ids"]) for p in out["paths"]} == {
        ("s", "m1", "t"),
        ("s", "m2", "t"),
    }
    assert len(s.find_paths("s", "t", limit=1)["paths"]) == 1


def test_invalidated_edges_are_not_walked():
    s = _store_with_chain()
    s.invalidate("a.py", "imports", "b.py")
    assert s.find_paths("a", "b")["paths"] == []
