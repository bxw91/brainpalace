from llama_index.core.graph_stores.types import EntityNode, Relation

from brainpalace_server.rehome.swap import rehome_graph_edge, rehome_graph_node
from brainpalace_server.storage.sqlite_graph_store import (
    SQLitePropertyGraphStore,
    _edge_id,
)


def _seed(store):
    store.upsert_nodes(
        [
            EntityNode(
                name="pkg", label="Folder", properties={"path": "/old/root/pkg"}
            ),
            EntityNode(
                name="mod.py",
                label="File",
                properties={"path": "/old/root/pkg/mod.py"},
            ),
        ]
    )
    # give them path ids matching code-symbol convention by re-upserting with ids
    store._conn.execute("UPDATE nodes SET id='/old/root/pkg' WHERE name='pkg'")
    store._conn.execute(
        "UPDATE nodes SET id='/old/root/pkg/mod.py' WHERE name='mod.py'"
    )
    store._conn.commit()
    store.upsert_relations(
        [
            Relation(
                source_id="/old/root/pkg",
                target_id="/old/root/pkg/mod.py",
                label="contains",
                properties={"source_file": "/old/root/pkg/mod.py"},
            ),
        ]
    )


def _swap_node(nid, props, old, new):
    swapped = rehome_graph_node(nid, props, old, new)
    return swapped.id, swapped.properties


def _swap_edge(source_id, target_id, label, source_file, old, new):
    swapped = rehome_graph_edge(source_id, target_id, label, source_file, old, new)
    return swapped.id, swapped.source_id, swapped.target_id, swapped.source_file


def test_graph_rehome_rekeys_nodes_and_edges(tmp_path):
    store = SQLitePropertyGraphStore(str(tmp_path / "g.db"))
    _seed(store)
    old, new = "/old/root", "/new/home"

    n_changed, e_changed = store.rehome(
        swap_node=lambda nid, props: _swap_node(nid, props, old, new),
        swap_edge=lambda s, t, lbl, sf: _swap_edge(s, t, lbl, sf, old, new),
    )
    assert (n_changed, e_changed) == (2, 1)

    node_ids = {r["id"] for r in store._conn.execute("SELECT id FROM nodes")}
    assert node_ids == {"/new/home/pkg", "/new/home/pkg/mod.py"}
    edge = store._conn.execute(
        "SELECT id, source_id, target_id, source_file FROM edges"
    ).fetchone()
    assert edge["source_id"] == "/new/home/pkg"
    assert edge["target_id"] == "/new/home/pkg/mod.py"
    assert edge["source_file"] == "/new/home/pkg/mod.py"
    assert edge["id"] == _edge_id("/new/home/pkg", "contains", "/new/home/pkg/mod.py")


def test_graph_rehome_idempotent_second_run_noop(tmp_path):
    store = SQLitePropertyGraphStore(str(tmp_path / "g.db"))
    _seed(store)
    old, new = "/old/root", "/new/home"

    def sn(nid, props):
        return _swap_node(nid, props, old, new)

    def se(s, t, lbl, sf):
        return _swap_edge(s, t, lbl, sf, old, new)

    store.rehome(swap_node=sn, swap_edge=se)
    n2, e2 = store.rehome(swap_node=sn, swap_edge=se)  # nothing under /old/root now
    assert (n2, e2) == (0, 0)
