"""Plan D Task 1 — node properties: merge API + edge-upserts must not clobber."""

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


class _N:
    def __init__(
        self,
        id: str,
        name: str,
        label: str = "Function",
        domain: str = "code",
        properties: dict | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.label = label
        self.domain = domain
        self.properties = properties or {}


def test_set_node_properties_merges_and_counts() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes([_N("f.py:foo", "foo")])
    n = store.set_node_properties({"f.py:foo": {"path": "f.py", "line": 3}})
    assert n == 1
    n = store.set_node_properties(
        {"f.py:foo": {"character": 4}, "missing:id": {"line": 1}}
    )
    assert n == 1  # unknown id skipped
    node = store.get_node("f.py:foo")
    assert node is not None
    assert node["properties"] == {"path": "f.py", "line": 3, "character": 4}


def test_empty_properties_upsert_preserves_existing() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes([_N("f.py:foo", "foo")])
    store.set_node_properties({"f.py:foo": {"line": 3}})
    # A later edge write re-upserts the node with empty properties (the _GNode
    # path) — the stored position must survive.
    store.upsert_nodes([_N("f.py:foo", "foo")])
    node = store.get_node("f.py:foo")
    assert node is not None and node["properties"] == {"line": 3}


def test_non_empty_properties_upsert_still_overwrites() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    store.upsert_nodes([_N("f.py:foo", "foo", properties={"line": 1})])
    store.upsert_nodes([_N("f.py:foo", "foo", properties={"line": 9})])
    node = store.get_node("f.py:foo")
    assert node is not None and node["properties"] == {"line": 9}


def test_get_node_unknown_returns_none() -> None:
    store = SQLitePropertyGraphStore(":memory:")
    assert store.get_node("nope") is None


def test_neighbors_nodes_carry_properties() -> None:
    store = SQLitePropertyGraphStore(":memory:")

    class _R:
        def __init__(self) -> None:
            self.label = "calls"
            self.source_id = "f.py:foo"
            self.target_id = "g.py:bar"
            self.properties: dict = {}

    store.upsert_nodes([_N("f.py:foo", "foo"), _N("g.py:bar", "bar")])
    store.upsert_relations([_R()])
    store.set_node_properties({"f.py:foo": {"path": "f.py", "line": 3}})
    out = store.neighbors(["f.py:foo"])
    by_id = {n["id"]: n for n in out["nodes"]}
    assert by_id["f.py:foo"]["properties"] == {"path": "f.py", "line": 3}
    assert by_id["g.py:bar"]["properties"] == {}
