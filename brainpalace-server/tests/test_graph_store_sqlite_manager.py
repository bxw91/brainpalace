"""GraphStoreManager wired to the SQLite backend (Phase 090)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import GraphStoreManager
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


@pytest.fixture(autouse=True)
def _enable_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    yield
    GraphStoreManager.reset_instance()


def _mgr(tmp_path: Path, store_type: str = "sqlite") -> GraphStoreManager:
    mgr = GraphStoreManager(persist_dir=tmp_path / "graph_index", store_type=store_type)
    mgr.initialize()
    return mgr


class TestDispatch:
    def test_sqlite_store_selected(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        assert mgr.store_type == "sqlite"
        assert isinstance(mgr.graph_store, SQLitePropertyGraphStore)

    def test_unknown_type_downgrades_to_simple(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path, store_type="kuzu")
        assert mgr.store_type == "simple"

    def test_add_triplet_and_query(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        assert mgr.add_triplet("parse_config", "calls", "load_yaml") is True
        store = mgr.graph_store
        triplets = store.get_triplets(entity_names=["parse_config"])
        assert len(triplets) == 1
        assert triplets[0][1].label == "calls"

    def test_counts_reflect_store(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        mgr.add_triplet("a", "rel", "b")
        mgr.add_triplet("b", "rel", "c")
        assert mgr.entity_count == 3
        assert mgr.relationship_count == 2


class TestPersistence:
    def test_triplet_survives_new_manager(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        mgr.add_triplet("a", "rel", "b")
        mgr.persist()
        GraphStoreManager.reset_instance()
        mgr2 = _mgr(tmp_path)
        assert len(mgr2.graph_store.get_triplets(entity_names=["a"])) == 1
        assert mgr2.relationship_count == 1


class TestTemporalManagerOps:
    def test_invalidate_then_query(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        mgr.add_triplet("d1", "supersedes", "d0")
        assert mgr.invalidate("d1", "supersedes", "d0") == 1
        assert mgr.graph_store.get_triplets(entity_names=["d1"]) == []

    def test_timeline(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        mgr.add_triplet("d1", "supersedes", "d0")
        tl = mgr.timeline("d1")
        assert len(tl) == 1

    def test_temporal_ops_noop_on_simple(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path, store_type="simple")
        mgr.add_triplet("a", "rel", "b")
        assert mgr.invalidate("a", "rel", "b") == 0
        assert mgr.timeline("a") == []


class TestMigration:
    def test_json_graph_migrated_to_sqlite(self, tmp_path: Path) -> None:
        """An existing simple JSON graph is replayed into SQLite on first use."""
        persist_dir = tmp_path / "graph_index"
        persist_dir.mkdir(parents=True)
        # Seed a simple-backend JSON graph by running a simple manager first.
        simple = GraphStoreManager(persist_dir=persist_dir, store_type="simple")
        simple.initialize()
        simple.add_triplet("legacy_a", "rel", "legacy_b")
        simple.persist()
        assert (persist_dir / "graph_store_llamaindex.json").exists()
        GraphStoreManager.reset_instance()

        # Now open as sqlite — migration should replay the JSON triplet.
        mgr = GraphStoreManager(persist_dir=persist_dir, store_type="sqlite")
        mgr.initialize()
        triplets = mgr.graph_store.get_triplets(entity_names=["legacy_a"])
        assert len(triplets) == 1
        # JSON left in place for rollback safety
        assert (persist_dir / "graph_store_llamaindex.json").exists()

    def test_migration_runs_once(self, tmp_path: Path) -> None:
        persist_dir = tmp_path / "graph_index"
        persist_dir.mkdir(parents=True)
        simple = GraphStoreManager(persist_dir=persist_dir, store_type="simple")
        simple.initialize()
        simple.add_triplet("x", "rel", "y")
        simple.persist()
        GraphStoreManager.reset_instance()

        mgr = GraphStoreManager(persist_dir=persist_dir, store_type="sqlite")
        mgr.initialize()
        mgr.persist()
        GraphStoreManager.reset_instance()
        # Reopen: should NOT double-import (count stays 1)
        mgr2 = GraphStoreManager(persist_dir=persist_dir, store_type="sqlite")
        mgr2.initialize()
        assert mgr2.relationship_count == 1
