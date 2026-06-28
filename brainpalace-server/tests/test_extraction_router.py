import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.extraction import router
from brainpalace_server.storage.extraction_pending import DocPendingStore


class _Graph:
    def __init__(self, ok=True):
        self.added = []
        self.ok = ok
        self.is_initialized = True

    def add_triplet(self, **kw):
        if not self.ok:
            return False  # mirrors graph off / not initialized
        self.added.append(kw)
        return True

    def persist(self):
        pass


class _Backend:
    is_initialized = True


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    store = DocPendingStore(tmp_path / "p.db")
    store.mark_pending("c1", "alpha")
    store.mark_pending("c2", "beta")
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
    c = TestClient(app)
    c._graph = graph  # type: ignore[attr-defined]
    c._store = store  # type: ignore[attr-defined]
    return c


def test_pending_returns_doc_items(client):
    r = client.get("/extraction/pending?limit=10")
    assert r.status_code == 200
    body = r.json()
    ids = {i["id"] for i in body["items"]}
    assert ids == {"c1", "c2"}
    assert body["doc_pending_total"] == 2
    assert all(i["source"] == "doc" and i["text"] for i in body["items"])


def test_submit_doc_writes_triplets_and_marks_done(client):
    r = client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": "c1",
            "triplets": [{"subject": "A", "predicate": "uses", "object": "B"}],
        },
    )
    assert r.status_code == 200
    assert r.json()["triplets_stored"] == 1 and r.json()["marked_done"] is True
    assert len(client._graph.added) == 1
    assert client._store.count_pending() == 1  # c1 done, c2 remains


def test_submit_doc_missing_chunk_id_400(client):
    r = client.post("/extraction/submit", json={"source": "doc", "triplets": []})
    assert r.status_code == 400


def test_pending_bad_source_400(client):
    r = client.get("/extraction/pending?source=bogus")
    assert r.status_code == 400
    assert "source must be one of" in r.json()["detail"]


def test_submit_session_missing_extraction_400(client):
    r = client.post("/extraction/submit", json={"source": "session"})
    assert r.status_code == 400


def test_submit_session_validates_and_stores(client, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from brainpalace_server.models.session_extract import SessionExtraction

    # Build a minimal valid extraction payload via the real model
    extraction_obj = SessionExtraction(
        session_id="test-session-123",
        summary="Did some work.",
    )
    extraction_dict = extraction_obj.model_dump()

    # Stub SessionExtractService so .store() is an AsyncMock
    mock_service_instance = MagicMock()
    mock_service_instance.store = AsyncMock(return_value=None)
    mock_service_class = MagicMock(return_value=mock_service_instance)
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.SessionExtractService",
        mock_service_class,
    )

    # Stub write_marker
    write_marker_calls = []
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.write_marker",
        lambda *a, **k: write_marker_calls.append(a),
    )

    # Stub get_embedding_generator (called inside submit)
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.get_embedding_generator",
        lambda: MagicMock(),
    )

    r = client.post(
        "/extraction/submit",
        json={"source": "session", "extraction": extraction_dict},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["marked_done"] is True
    assert body["id"] == "test-session-123"
    mock_service_instance.store.assert_called_once()
    assert len(write_marker_calls) == 1


def test_submit_doc_graph_not_ready_stays_pending(client):
    # Graph not yet initialized (transient) -> chunk must NOT be evicted, so a
    # later drain retries once the graph is available (review must-fix #1).
    client._graph.is_initialized = False
    client._graph.ok = False
    r = client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": "c1",
            "triplets": [{"subject": "A", "predicate": "uses", "object": "B"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["triplets_stored"] == 0
    assert body["marked_done"] is False
    assert client._store.count_pending() == 2  # nothing evicted


def test_submit_doc_terminal_triplet_failure_marks_done(client):
    # Graph IS ready but a triplet won't store (terminal per-triplet failure, e.g.
    # a malformed entity). The chunk must be marked done anyway — re-draining would
    # re-submit the same failing triplet forever (finding 3-1: no livelock).
    client._graph.is_initialized = True
    client._graph.ok = False  # add_triplet returns False for every triplet
    r = client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": "c1",
            "triplets": [{"subject": "", "predicate": "uses", "object": "B"}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["triplets_stored"] == 0
    assert body["marked_done"] is True  # evicted — no endless re-drain loop
    assert client._store.count_pending() == 1  # c1 done, c2 remains


def test_submit_session_backend_not_ready_503(client):
    client.app.state.storage_backend = None
    r = client.post(
        "/extraction/submit",
        json={"source": "session", "extraction": {"session_id": "s1"}},
    )
    assert r.status_code == 503


def test_submit_session_write_marker_oserror_still_200(client, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from brainpalace_server.models.session_extract import SessionExtraction

    extraction_dict = SessionExtraction(session_id="s-marker", summary="x").model_dump()
    svc = MagicMock()
    svc.store = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.SessionExtractService",
        MagicMock(return_value=svc),
    )
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.get_embedding_generator",
        lambda: MagicMock(),
    )

    def _raise(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.write_marker", _raise
    )
    r = client.post(
        "/extraction/submit",
        json={"source": "session", "extraction": extraction_dict},
    )
    assert r.status_code == 200  # store succeeded; marker failure must not 500
    assert r.json()["marked_done"] is False


def test_pending_limit_is_clamped(client, monkeypatch):
    # 3-7: a huge limit must not load an unbounded batch with text into memory.
    captured = {}
    orig = client._store.select_pending

    def spy(limit):
        captured["limit"] = limit
        return orig(limit)

    monkeypatch.setattr(client._store, "select_pending", spy)
    r = client.get("/extraction/pending?limit=1000000")
    assert r.status_code == 200
    assert captured["limit"] <= 100


def test_submit_rejects_oversized_triplet_payload(client):
    # 3-7: cap the triplet list so a buggy client can't flood add_triplet.
    payload = {
        "source": "doc",
        "chunk_id": "c1",
        "triplets": [
            {"subject": "a", "predicate": "calls", "object": "b"} for _ in range(1001)
        ],
    }
    r = client.post("/extraction/submit", json=payload)
    assert r.status_code == 400


def test_pending_all_interleaves_docs_and_sessions(client, monkeypatch):
    # Doc backlog already exceeds a small limit; sessions must still surface.
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.pending_sessions",
        lambda *a, **k: [("s1", "/a/s1.jsonl"), ("s2", "/a/s2.jsonl")],
    )
    r = client.get("/extraction/pending?limit=2&source=all")
    assert r.status_code == 200
    sources = {i["source"] for i in r.json()["items"]}
    assert sources == {"doc", "session"}  # neither starved


def test_extraction_text_returns_pending_text_then_404(client):
    assert client.get("/extraction/text/c1").json()["text"] == "alpha"
    client._store.mark_done("c1")
    assert client.get("/extraction/text/c1").status_code == 404
    assert client.get("/extraction/text/nope").status_code == 404


def test_submit_already_done_chunk_is_noop(client):
    p = {
        "source": "doc",
        "chunk_id": "c1",
        "triplets": [{"subject": "A", "predicate": "calls", "object": "B"}],
    }
    assert client.post("/extraction/submit", json=p).status_code == 200
    client._store.mark_done("c1")  # provider drained it meanwhile
    before = len(client._graph.added)  # _graph spy: list of added-edge kwargs
    r = client.post("/extraction/submit", json=p)  # subagent submits late
    assert r.status_code == 200
    assert r.json()["triplets_stored"] == 0  # dedup → nothing new
    assert len(client._graph.added) == before  # no duplicate edge appended
