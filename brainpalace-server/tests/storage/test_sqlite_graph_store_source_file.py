from llama_index.core.graph_stores.types import EntityNode, Relation

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _store():
    return SQLitePropertyGraphStore(path=":memory:")


def test_edges_have_source_file_column():
    s = _store()
    cols = {r[1] for r in s._conn.execute("PRAGMA table_info(edges)")}
    assert "source_file" in cols


def test_upsert_relations_persists_source_file():
    s = _store()
    a, b = EntityNode(name="A"), EntityNode(name="B")
    s.upsert_nodes([a, b])
    rel = Relation(
        label="calls",
        source_id=a.id,
        target_id=b.id,
        properties={"source_file": "pkg/mod.py"},
    )
    s.upsert_relations([rel])
    row = s._conn.execute("SELECT source_file FROM edges").fetchone()
    assert row[0] == "pkg/mod.py"
