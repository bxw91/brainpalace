"""§3 — a doc re-submit purges the chunk's prior triplets (no stale buildup)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.extraction import router
from brainpalace_server.storage.extraction_pending import DocPendingStore
from brainpalace_server.storage.graph_store import GraphStoreManager


@pytest.fixture
def harness(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    store = DocPendingStore(tmp_path / "p.db")
    app.state.doc_pending_store = store
    app.state.project_root = str(tmp_path)
    app.state.extraction_archive_dir = str(tmp_path)
    mgr = GraphStoreManager(persist_dir=tmp_path, store_type="sqlite")
    mgr.initialize()
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.get_graph_store_manager",
        lambda: mgr,
    )
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.pending_sessions",
        lambda *a, **k: [],
    )
    return TestClient(app), store, mgr


def _submit(client, chunk_id, triplets):
    return client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": chunk_id,
            "triplets": [
                {"subject": s, "predicate": p, "object": o} for s, p, o in triplets
            ],
        },
    )


def _valid_edges(mgr):
    return {
        (r[0], r[1], r[2])
        for r in mgr._graph_store._conn.execute(
            "SELECT source_id, label, target_id FROM edges " "WHERE valid_until IS NULL"
        )
    }


def test_resubmit_purges_stale_doc_triplets(harness):
    client, store, mgr = harness
    store.mark_pending("c1", "alpha")
    assert _submit(client, "c1", [("A", "references", "B")]).status_code == 200
    assert ("A", "references", "B") in _valid_edges(mgr)
    # Re-extraction of the same chunk drops the old fact, adds a new one.
    store.mark_pending("c1", "alpha v2")
    assert _submit(client, "c1", [("A", "references", "C")]).status_code == 200
    edges = _valid_edges(mgr)
    assert ("A", "references", "C") in edges
    assert ("A", "references", "B") not in edges
    # Orphaned node B was swept, in the doc domain only.
    ids = {r[0] for r in mgr._graph_store._conn.execute("SELECT id FROM nodes")}
    assert "B" not in ids


def test_doc_triplets_carry_domain_and_source_file(harness):
    client, store, mgr = harness
    store.mark_pending("c9", "text")
    _submit(client, "c9", [("X", "references", "Y")])
    row = mgr._graph_store._conn.execute(
        "SELECT source_file FROM edges WHERE valid_until IS NULL"
    ).fetchone()
    assert row["source_file"] == "c9"
    dom = mgr._graph_store._conn.execute(
        "SELECT domain FROM nodes WHERE id = 'X'"
    ).fetchone()
    assert dom["domain"] == "doc"


def test_domain_isolation_code_untouched_by_doc_purge(harness):
    client, store, mgr = harness
    mgr.add_triplet(
        "a",
        "calls",
        "b",
        subject_id="f.py:a",
        object_id="f.py:b",
        subject_name="a",
        object_name="b",
        source_file="c1",
        domain="code",  # same source_file string, code domain
    )
    store.mark_pending("c1", "alpha")
    _submit(client, "c1", [("A", "references", "B")])
    # The code edge shares the source_file string but lives in domain=code —
    # the doc-scoped purge must not close it.
    assert ("f.py:a", "calls", "f.py:b") in _valid_edges(mgr)
