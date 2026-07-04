"""Plan B Task 2 — edge_properties pass-through on manager add_triplet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture(autouse=True)
def _enable_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    yield
    GraphStoreManager.reset_instance()


def _mgr(tmp_path: Path) -> GraphStoreManager:
    mgr = GraphStoreManager(persist_dir=tmp_path / "graph_index", store_type="sqlite")
    mgr.initialize()
    return mgr


def _edge_row(mgr: GraphStoreManager) -> dict:
    row = mgr.graph_store._conn.execute(
        "SELECT properties, source_file, valid_until FROM edges"
    ).fetchone()
    return {
        "properties": json.loads(row["properties"] or "{}"),
        "source_file": row["source_file"],
        "valid_until": row["valid_until"],
    }


def test_edge_properties_stored(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.add_triplet(
        "note", "references", "auth.py", edge_properties={"resolved": True}
    )
    assert _edge_row(mgr)["properties"]["resolved"] is True


def test_reserved_keys_stripped(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.add_triplet(
        "note",
        "references",
        "auth.py",
        source_file="chunk_1",
        edge_properties={
            "resolved": True,
            "source_file": "evil",
            "source_chunk_id": "evil",
            "valid_from": "1970-01-01T00:00:00+00:00",
            "valid_until": "1970-01-01T00:00:00+00:00",
        },
    )
    row = _edge_row(mgr)
    assert row["source_file"] == "chunk_1"  # kwarg wins, not the smuggled value
    assert row["valid_until"] is None  # edge stays open
    assert row["properties"] == {"resolved": True}


def test_default_unchanged(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    assert mgr.add_triplet("a", "rel", "b", source_file="f")
    assert "resolved" not in _edge_row(mgr)["properties"]
