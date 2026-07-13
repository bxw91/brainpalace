# tests/rehome/test_build_rehome_stores_graph.py
"""Graph blocker fix: build_rehome_stores wires the rehome-capable SQLite graph
store when the sqlite backend is active, so phase-4 graph rehome actually runs on
the live server (previously always None)."""

from types import SimpleNamespace

from brainpalace_server.config.settings import settings
from brainpalace_server.rehome.quarantine import build_rehome_stores
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


def _seed_graph_db(state_dir):
    graph_dir = state_dir / "data" / "graph_index"
    graph_dir.mkdir(parents=True, exist_ok=True)
    # Constructing the store creates/opens the sqlite file.
    SQLitePropertyGraphStore(str(graph_dir / "graph_store.db"))
    return graph_dir / "graph_store.db"


def test_graph_wired_when_sqlite_backend(tmp_path, monkeypatch):
    _seed_graph_db(tmp_path)
    monkeypatch.setattr(settings, "GRAPH_STORE_TYPE", "sqlite", raising=False)
    stores = build_rehome_stores(SimpleNamespace(), tmp_path)
    assert isinstance(stores.graph, SQLitePropertyGraphStore)
    assert hasattr(stores.graph, "rehome")  # phase-4 callable is present


def test_graph_none_when_simple_backend(tmp_path, monkeypatch):
    _seed_graph_db(tmp_path)  # db present, but backend is simple -> no A5 rehome
    monkeypatch.setattr(settings, "GRAPH_STORE_TYPE", "simple", raising=False)
    stores = build_rehome_stores(SimpleNamespace(), tmp_path)
    assert stores.graph is None


def test_graph_none_when_sqlite_but_no_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GRAPH_STORE_TYPE", "sqlite", raising=False)
    stores = build_rehome_stores(SimpleNamespace(), tmp_path)
    assert stores.graph is None  # nothing indexed yet -> no-op


def test_simple_backend_wires_graph_simple_json(tmp_path, monkeypatch):
    graph_dir = tmp_path / "data" / "graph_index"
    graph_dir.mkdir(parents=True)
    json_path = graph_dir / "graph_store_llamaindex.json"
    json_path.write_text('{"nodes": {}, "relations": {}, "triplets": []}')
    monkeypatch.setattr(settings, "GRAPH_STORE_TYPE", "simple", raising=False)
    stores = build_rehome_stores(SimpleNamespace(), tmp_path)
    assert stores.graph is None  # no sqlite handle for simple
    assert stores.graph_simple_json == str(json_path)  # JSON wired for phase-4 swap


def test_simple_backend_no_json_leaves_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GRAPH_STORE_TYPE", "simple", raising=False)
    stores = build_rehome_stores(SimpleNamespace(), tmp_path)
    assert stores.graph is None and stores.graph_simple_json is None
