from llama_index.core.graph_stores.types import EntityNode, Relation

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _seed(s, src):
    a = EntityNode(name="f.py:foo")
    b = EntityNode(name="f.py:bar")
    s.upsert_nodes([a, b])
    s.upsert_relations(
        [
            Relation(
                label="contains",
                source_id=a.id,
                target_id=b.id,
                properties={"source_file": src},
            )
        ]
    )
    return a, b


def test_invalidate_by_source_file_marks_edges_invalid():
    s = SQLitePropertyGraphStore(path=":memory:")
    _seed(s, "f.py")
    n = s.invalidate_by_source_file("f.py", domain="code")
    assert n == 1
    # edge_count default excludes invalid
    assert s.edge_count() == 0
    assert s.edge_count(include_invalid=True) == 1


def test_sweep_orphan_nodes_removes_nodes_without_valid_edges():
    s = SQLitePropertyGraphStore(path=":memory:")
    _seed(s, "f.py")
    s.invalidate_by_source_file("f.py", domain="code")
    removed = s.sweep_orphan_nodes(domain="code")
    assert removed == 2
    assert s.node_count() == 0
