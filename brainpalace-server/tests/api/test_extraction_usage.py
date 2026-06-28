"""Task-3 Step-1: subagent submit records STORED triplets, not claimed (§6-F2)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import brainpalace_server.services.usage_metrics as um
from brainpalace_server.api.routers.extraction import router
from brainpalace_server.storage.extraction_pending import DocPendingStore
from brainpalace_server.storage.usage_metrics_store import UsageMetricsStore


class _Graph:
    def __init__(self, ok=True):
        self.added = []
        self.ok = ok
        self.is_initialized = True

    def add_triplet(self, **kw):
        if not self.ok:
            return False
        self.added.append(kw)
        return True

    def persist(self):
        pass


class _Backend:
    is_initialized = True


@pytest.fixture
def bare_app(tmp_path, monkeypatch):
    """Minimal FastAPI app with extraction router, ready graph and pending store."""
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    store = DocPendingStore(tmp_path / "p.db")
    store.mark_pending("c1", "alpha")
    app.state.doc_pending_store = store
    app.state.project_root = str(tmp_path)
    app.state.extraction_archive_dir = str(tmp_path)
    app.state.storage_backend = _Backend()
    graph = _Graph()
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.get_graph_store_manager",
        lambda: graph,
    )
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.pending_sessions",
        lambda *a, **k: [],
    )
    return app


def test_submit_records_stored_triplets_not_claimed(tmp_path, bare_app):
    """A doc submit records the STORED delta; a late/dup submit records 0."""
    store = UsageMetricsStore(tmp_path / "u.db")
    um.set_usage_store(store)
    try:
        client = TestClient(bare_app)
        payload = {
            "source": "doc",
            "chunk_id": "c1",
            "triplets": [{"subject": "A", "predicate": "calls", "object": "B"}],
        }
        r = client.post("/extraction/submit", json=payload)
        assert r.json()["triplets_stored"] == 1
        # second submit on now-drained chunk → no-op, triplets_stored == 0
        r2 = client.post("/extraction/submit", json=payload)
        assert r2.json()["triplets_stored"] == 0
        totals, _ = store.aggregate(since_bucket=0)
        sub = [t for t in totals if t["channel"] == "subagent"]
        # exactly one stored triplet metered across BOTH submits (no double count)
        assert sum(t["triplets"] for t in sub) == 1
    finally:
        um.set_usage_store(None)
