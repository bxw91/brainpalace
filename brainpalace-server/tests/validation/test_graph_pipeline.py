"""E2E validation: graph build → query → persist (Phases 090/100).

Keyless — drives the REAL GraphStoreManager(sqlite) + GraphIndexManager over
synthetic code-doc dicts (no embeddings). Proves the persistent backend, the
build pipeline, GRAPH retrieval, and typed-node filtering compose end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture(autouse=True)
def _enable_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    monkeypatch.setattr(settings, "GRAPH_USE_CODE_METADATA", True)
    GraphStoreManager.reset_instance()
    yield
    GraphStoreManager.reset_instance()


def _mgr(tmp_path: Path) -> GraphStoreManager:
    mgr = GraphStoreManager(persist_dir=tmp_path / "g", store_type="sqlite")
    mgr.initialize()
    return mgr


def _code_doc(chunk_id: str, symbol: str, imports: list[str], file_path: str) -> dict:
    return {
        "text": f"def {symbol}(): ...",
        "chunk_id": chunk_id,
        "metadata": {
            "source_type": "code",
            "symbol_name": symbol,
            "symbol_type": "function",
            "file_path": file_path,
            "language": "python",
            "imports": imports,
        },
    }


def test_build_query_persist_sqlite(tmp_path: Path) -> None:
    mgr = _mgr(tmp_path)
    gi = GraphIndexManager(graph_store=mgr)

    docs = [
        _code_doc("c1", "parse_config", ["yaml"], "cfg.py"),
        _code_doc("c2", "load_yaml", ["io"], "cfg.py"),
    ]
    written = gi.build_from_documents(docs)
    assert written > 0
    assert mgr.relationship_count > 0

    # GRAPH retrieval finds the import edge
    results = gi.query("parse_config")
    assert any(
        r["subject"] == "parse_config" and r["object"] == "yaml" for r in results
    )

    # 090 persistence: a fresh manager on the same dir sees the triplets
    GraphStoreManager.reset_instance()
    mgr2 = _mgr(tmp_path)
    assert mgr2.relationship_count > 0
    gi2 = GraphIndexManager(graph_store=mgr2)
    assert gi2.query("parse_config")


def test_typed_nodes_queryable_by_type(tmp_path: Path) -> None:
    """100: typed session triplets are filterable via query_by_type."""
    mgr = _mgr(tmp_path)
    gi = GraphIndexManager(graph_store=mgr)
    mgr.add_triplet(
        "decision_42",
        "supersedes",
        "decision_17",
        subject_type="Decision",
        object_type="Decision",
        source_chunk_id="s1",
    )
    typed = gi.query_by_type("decision_42", entity_types=["Decision"])
    assert any(r["subject"] == "decision_42" for r in typed)
