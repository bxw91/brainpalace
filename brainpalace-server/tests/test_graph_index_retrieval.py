"""Tests for graph retrieval against the property-graph store (Phase J)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def populated_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager(persist_dir=tmp_path / "g", store_type="simple")
    mgr.initialize()
    mgr.add_triplet(
        "parse_config",
        "calls",
        "load_yaml",
        subject_type="Function",
        object_type="Function",
        source_chunk_id="chunk_1",
    )
    yield mgr
    GraphStoreManager.reset_instance()


def test_find_entity_relationships_substring_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Query token matches a longer node name via substring (regression: J5)."""
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager(persist_dir=tmp_path / "g", store_type="simple")
    mgr.initialize()
    mgr.add_triplet("usePageRotation", "imports", "react")
    try:
        gi = GraphIndexManager(graph_store=mgr)
        results = gi._find_entity_relationships("rotation", depth=1, max_results=10)
        assert any(r["subject"] == "usePageRotation" for r in results)
        assert all(r["graph_score"] is not None for r in results)
    finally:
        GraphStoreManager.reset_instance()


def test_find_entity_relationships_returns_graph_score(populated_graph) -> None:
    """Retrieving a known entity yields a result with a real graph_score."""
    gi = GraphIndexManager(graph_store=populated_graph)
    results = gi._find_entity_relationships("parse_config", depth=1, max_results=10)

    assert len(results) >= 1
    hit = results[0]
    assert hit["subject"] == "parse_config"
    assert hit["predicate"] == "calls"
    assert hit["object"] == "load_yaml"
    assert hit["graph_score"] is not None
    assert hit["subject_type"] == "Function"
    assert hit["object_type"] == "Function"
    assert hit["source_chunk_id"] == "chunk_1"
