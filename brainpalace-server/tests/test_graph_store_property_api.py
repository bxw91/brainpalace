"""Tests for GraphStoreManager against the property-graph API (Phase J)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture(params=["simple", "sqlite"])
def graph_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    """A fresh, initialized GraphStoreManager — run against both backends.

    Phase 090: the property-graph API contract must hold identically on the
    in-memory ``simple`` backend and the persistent ``sqlite`` backend.
    """
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager(
        persist_dir=tmp_path / "graph_index", store_type=request.param
    )
    mgr.initialize()
    yield mgr
    GraphStoreManager.reset_instance()


class TestAddTriplet:
    def test_add_triplet_stores_in_graph(self, graph_manager) -> None:
        """add_triplet actually persists a node/relation into the store."""
        ok = graph_manager.add_triplet(
            subject="parse_config",
            predicate="calls",
            obj="load_yaml",
            subject_type="Function",
            object_type="Function",
        )
        assert ok is True

        store = graph_manager.graph_store
        node_names = {n.name for n in store.get()}
        assert "parse_config" in node_names
        assert "load_yaml" in node_names
        triplets = store.get_triplets(entity_names=["parse_config"])
        assert len(triplets) == 1
        subj, rel, obj = triplets[0]
        assert subj.name == "parse_config"
        assert rel.label == "calls"
        assert obj.name == "load_yaml"

    def test_add_triplet_counts_reflect_store(self, graph_manager) -> None:
        """entity/relationship counts are derived from the store, not fabricated."""
        graph_manager.add_triplet("a", "rel", "b")
        graph_manager.add_triplet("b", "rel", "c")
        assert graph_manager.entity_count == 3
        assert graph_manager.relationship_count == 2

    def test_add_triplet_skipped_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_triplet is a no-op when ENABLE_GRAPH_INDEX is False."""
        monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", False)
        GraphStoreManager.reset_instance()
        mgr = GraphStoreManager(persist_dir=tmp_path / "g", store_type="simple")
        mgr.initialize()
        assert mgr.add_triplet("a", "rel", "b") is False
        GraphStoreManager.reset_instance()


class TestPersistLoadRoundTrip:
    def test_persist_then_load_preserves_triplets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A triplet survives persist + a fresh load (new manager instance)."""
        monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
        persist_dir = tmp_path / "graph_index"

        GraphStoreManager.reset_instance()
        mgr1 = GraphStoreManager(persist_dir=persist_dir, store_type="simple")
        mgr1.initialize()
        mgr1.add_triplet("alpha", "uses", "beta")
        mgr1.persist()

        GraphStoreManager.reset_instance()
        mgr2 = GraphStoreManager(persist_dir=persist_dir, store_type="simple")
        mgr2.initialize()
        loaded = mgr2.load()

        assert loaded is True
        assert mgr2.entity_count == 2
        assert mgr2.relationship_count == 1
        names = {n.name for n in mgr2.graph_store.get()}
        assert names == {"alpha", "beta"}
        GraphStoreManager.reset_instance()

    def test_persisted_store_file_is_not_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """graph_store_llamaindex.json contains the upserted data after persist."""
        import json

        monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
        persist_dir = tmp_path / "graph_index"
        GraphStoreManager.reset_instance()
        mgr = GraphStoreManager(persist_dir=persist_dir, store_type="simple")
        mgr.initialize()
        mgr.add_triplet("x", "rel", "y")
        mgr.persist()

        store_file = persist_dir / "graph_store_llamaindex.json"
        assert store_file.exists()
        data = json.loads(store_file.read_text())
        assert data.get("nodes"), "persisted store has no nodes — Phase J regression"
        GraphStoreManager.reset_instance()
