"""search_nodes + neighbors subgraph reads (dashboard plan 06)."""

from types import SimpleNamespace

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _node(nid: str, name: str, label: str):
    return SimpleNamespace(id=nid, name=name, label=label, properties={})


def _rel(src: str, label: str, tgt: str):
    return SimpleNamespace(source_id=src, label=label, target_id=tgt, properties={})


def _seeded() -> SQLitePropertyGraphStore:
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes(
        [
            _node("n1", "QueryService", "Class"),
            _node("n2", "execute_query", "Function"),
            _node("n3", "QueryRequest", "Class"),
            _node("n4", "unrelated_thing", "Function"),
        ]
    )
    store.upsert_relations(
        [
            _rel("n1", "contains", "n2"),
            _rel("n2", "uses", "n3"),
        ]
    )
    return store


def test_search_nodes_matches_substring_with_degree():
    store = _seeded()
    rows = store.search_nodes("query")
    names = {r["name"] for r in rows}
    assert names == {"QueryService", "execute_query", "QueryRequest"}
    by_name = {r["name"]: r for r in rows}
    assert by_name["execute_query"]["degree"] == 2
    assert by_name["QueryService"]["degree"] == 1
    # ordered by degree desc
    assert rows[0]["name"] == "execute_query"


def test_search_nodes_respects_limit():
    store = _seeded()
    assert len(store.search_nodes("query", limit=1)) == 1


def test_neighbors_returns_touching_subgraph():
    store = _seeded()
    sub = store.neighbors(["n2"])
    node_ids = {n["id"] for n in sub["nodes"]}
    assert node_ids == {"n1", "n2", "n3"}
    edge_pairs = {(e["source"], e["target"]) for e in sub["edges"]}
    assert edge_pairs == {("n1", "n2"), ("n2", "n3")}
    # Each node carries its true active-edge degree so the browser ranks
    # fan-out by real hubs (deep expansion) instead of leaves.
    by_id = {n["id"]: n for n in sub["nodes"]}
    assert by_id["n2"]["degree"] == 2
    assert by_id["n1"]["degree"] == 1
    assert by_id["n3"]["degree"] == 1


def test_neighbors_excludes_invalidated_edges():
    store = _seeded()
    store.invalidate("QueryService", "contains", "execute_query")
    sub = store.neighbors(["n2"])
    edge_pairs = {(e["source"], e["target"]) for e in sub["edges"]}
    assert edge_pairs == {("n2", "n3")}


def test_neighbors_empty_input():
    store = _seeded()
    assert store.neighbors([]) == {"nodes": [], "edges": []}


def test_search_nodes_escapes_like_wildcards():
    """'_' in the search text must be treated as a literal, not a LIKE wildcard."""
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes(
        [
            # Name contains a literal underscore — must match when searching "my_fn"
            _node("a1", "my_fn", "Function"),
            # Would be a false positive if '_' were a wildcard (myXfn matches my.fn)
            _node("a2", "myXfn", "Function"),
        ]
    )
    results = store.search_nodes("my_fn")
    names = {r["name"] for r in results}
    assert "my_fn" in names, "literal underscore node must be found"
    assert "myXfn" not in names, "wildcard mis-match must NOT appear in results"
