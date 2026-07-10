from pathlib import Path

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _store(tmp_path):
    return SQLitePropertyGraphStore(str(tmp_path / "graph_store.db"))


def _insert_node(store, nid, name, sensitivity="normal"):
    store._conn.execute(
        "INSERT INTO nodes (id, name, label, properties, domain, sensitivity) "
        "VALUES (?, ?, 'Class', '{}', 'code', ?)",
        (nid, name, sensitivity),
    )
    store._conn.commit()


def test_nodes_sensitivity_column_exists(tmp_path):
    store = _store(tmp_path)
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)")}
    assert "sensitivity" in cols


def test_search_nodes_hides_sensitive_by_default(tmp_path):
    store = _store(tmp_path)
    _insert_node(store, "n1", "AuthToken")
    _insert_node(store, "n2", "AuthSecret", sensitivity="private")
    names = {r["name"] for r in store.search_nodes("Auth", limit=10)}
    assert names == {"AuthToken"}


def test_search_nodes_reveals_when_allowed(tmp_path):
    store = _store(tmp_path)
    _insert_node(store, "n1", "AuthToken")
    _insert_node(store, "n2", "AuthSecret", sensitivity="private")
    names = {
        r["name"] for r in store.search_nodes("Auth", limit=10, include_sensitive=True)
    }
    assert names == {"AuthToken", "AuthSecret"}


def _insert_edge(store, sid, tid, label="calls"):
    store._conn.execute(
        "INSERT INTO edges (id, source_id, target_id, label, valid_from, valid_until) "
        "VALUES (?, ?, ?, ?, '2026-01-01', NULL)",
        (f"{sid}->{tid}", sid, tid, label),
    )
    store._conn.commit()


def test_get_triplets_hides_edge_to_sensitive_endpoint(tmp_path):
    store = _store(tmp_path)
    _insert_node(store, "n1", "AuthToken")  # normal, matched
    _insert_node(store, "n2", "AuthSecret", sensitivity="private")  # private endpoint
    _insert_edge(store, "n1", "n2")
    # default-deny: the edge to the private node is dropped (subject matched, but
    # object is sensitive) — no leak of "AuthSecret" via the far endpoint.
    trips = store.get_triplets(entity_names=["AuthToken"], include_sensitive=False)
    assert trips == []
    # revealed with the flag
    trips = store.get_triplets(entity_names=["AuthToken"], include_sensitive=True)
    assert len(trips) == 1


def test_get_triplets_default_reveals_for_internal_callers(tmp_path):
    store = _store(tmp_path)
    _insert_node(store, "n1", "AuthToken")
    _insert_node(store, "n2", "AuthSecret", sensitivity="private")
    _insert_edge(store, "n1", "n2")
    # default kwarg is True — migration/replay callers keep full visibility
    assert len(store.get_triplets(entity_names=["AuthToken"])) == 1


def test_legacy_nodes_table_migrates(tmp_path):
    import sqlite3

    db = tmp_path / "legacy_graph.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, label TEXT, "
        "properties TEXT, domain TEXT NOT NULL DEFAULT 'code')"
    )
    conn.execute(
        "CREATE TABLE edges (id TEXT PRIMARY KEY, source_id TEXT, "
        "target_id TEXT, label TEXT, properties TEXT, source_file TEXT, "
        "valid_from TEXT, valid_until TEXT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    store = SQLitePropertyGraphStore(str(db))  # must ALTER-add sensitivity
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)")}
    assert "sensitivity" in cols


def _manager(tmp_path, monkeypatch):
    from brainpalace_server.config import settings
    from brainpalace_server.storage.graph_store import GraphStoreManager

    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    mgr = GraphStoreManager(Path(tmp_path))
    mgr._graph_store = _store(tmp_path)
    return mgr


def test_manager_search_nodes_default_deny(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _insert_node(mgr._graph_store, "n1", "AuthToken")
    _insert_node(mgr._graph_store, "n2", "AuthSecret", sensitivity="private")
    names = {r["name"] for r in mgr.search_nodes("Auth", limit=10)}
    assert names == {"AuthToken"}


def test_manager_search_nodes_reveals_when_allowed(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch)
    _insert_node(mgr._graph_store, "n1", "AuthToken")
    _insert_node(mgr._graph_store, "n2", "AuthSecret", sensitivity="private")
    names = {
        r["name"] for r in mgr.search_nodes("Auth", limit=10, include_sensitive=True)
    }
    assert names == {"AuthToken", "AuthSecret"}
