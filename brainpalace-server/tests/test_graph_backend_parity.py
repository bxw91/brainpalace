"""GRAPH-mode retrieval parity: sqlite must match simple (Phase 090).

The persistent SQLite backend is only safe to adopt if it is *retrieval-
transparent* — i.e. GRAPH-mode queries return the same triplets the in-memory
``simple`` backend does for the same graph. This drives the real
``GraphIndexManager.query`` path (the same code the query router hits) over both
backends seeded with an identical triplet set and asserts the result sets are
equal.

Keyless and deterministic (no embeddings / no OpenAI), so it runs inside
``pr-qa-gate`` — unlike the full ``task eval`` harness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.indexing.graph_index import GraphIndexManager
from brainpalace_server.storage.graph_store import GraphStoreManager

# A small but varied graph: code call edges + session-style decision edges.
TRIPLETS = [
    ("parse_config", "calls", "load_yaml", "Function", "Function", "c1"),
    ("load_yaml", "reads", "config_file", "Function", "File", "c2"),
    ("decision_42", "supersedes", "decision_17", "Decision", "Decision", "c3"),
    ("decision_42", "touches", "auth.py", "Decision", "File", "c4"),
    ("error_timeout", "fixed_by", "decision_42", "Error", "Decision", "c5"),
]

QUERIES = [
    "parse_config",
    "load_yaml",
    "decision_42",
    "auth.py",
    "error_timeout",
    "nonexistent_entity",
]


def _result_key(r: dict) -> tuple:
    return (
        r.get("subject"),
        r.get("predicate"),
        r.get("object"),
        r.get("source_chunk_id"),
    )


def _build(tmp_path: Path, store_type: str) -> GraphIndexManager:
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager(
        persist_dir=tmp_path / f"graph_{store_type}", store_type=store_type
    )
    mgr.initialize()
    for s, p, o, st, ot, cid in TRIPLETS:
        mgr.add_triplet(s, p, o, subject_type=st, object_type=ot, source_chunk_id=cid)
    mgr.persist()
    return GraphIndexManager(graph_store=mgr)


def test_sqlite_graph_results_match_simple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)

    simple = _build(tmp_path, "simple")
    simple_results = {q: simple.query(q) for q in QUERIES}
    GraphStoreManager.reset_instance()

    sqlite = _build(tmp_path, "sqlite")
    sqlite_results = {q: sqlite.query(q) for q in QUERIES}
    GraphStoreManager.reset_instance()

    for q in QUERIES:
        simple_keys = {_result_key(r) for r in simple_results[q]}
        sqlite_keys = {_result_key(r) for r in sqlite_results[q]}
        assert sqlite_keys == simple_keys, (
            f"GRAPH parity mismatch for query {q!r}:\n"
            f"  simple-only: {simple_keys - sqlite_keys}\n"
            f"  sqlite-only: {sqlite_keys - simple_keys}"
        )


def test_sqlite_finds_expected_relationships(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: the parity isn't 'both return nothing'."""
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    sqlite = _build(tmp_path, "sqlite")
    results = sqlite.query("decision_42")
    GraphStoreManager.reset_instance()
    keys = {_result_key(r) for r in results}
    assert ("decision_42", "supersedes", "decision_17", "c3") in keys
