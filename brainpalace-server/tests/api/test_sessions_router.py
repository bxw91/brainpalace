"""Sessions router tests (Phase 050 + 060). Keyless minimal app."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.sessions import router
from brainpalace_server.config.session_config import SessionIndexingConfig


class FakeService:
    async def index_project(self, project_root, config, home=None):  # noqa: ANN001,ANN201
        return {"enabled": True, "files": 2, "files_skipped_old": 0, "sessions": {}}


class FakeStore:
    is_initialized = True

    def __init__(self) -> None:
        self.docs: dict = {}

    async def delete_by_metadata(self, where):  # noqa: ANN001,ANN201
        return 0

    async def upsert_documents(self, ids, embeddings, documents, metadatas):  # noqa: ANN001,ANN201
        for cid in ids:
            self.docs[cid] = True


class FakeEmbedder:
    async def embed_chunks(self, chunks, progress=None):  # noqa: ANN001,ANN201
        return [[0.0] for _ in chunks]


def _app(service, config=None) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    app.state.session_index_service = service
    app.state.session_indexing_config = config
    app.state.project_root = "/work/proj"
    return app


def test_reindex_returns_summary() -> None:
    c = TestClient(_app(FakeService(), SessionIndexingConfig(enabled=True)))
    r = c.post("/sessions/reindex")
    assert r.status_code == 200
    assert r.json()["files"] == 2


def test_503_when_service_absent() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    app.state.session_index_service = None
    assert TestClient(app).post("/sessions/reindex").status_code == 503


def test_extract_persists_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    monkeypatch.setattr(
        "brainpalace_server.indexing.get_embedding_generator",
        lambda: FakeEmbedder(),
    )
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    app.state.storage_backend = store
    app.state.project_root = ""  # skip digest write in the test
    c = TestClient(app)
    r = c.post(
        "/sessions/extract",
        json={
            "session_id": "s1",
            "summary": "did the thing",
            "decisions": [{"text": "use a hosted store"}],
            "triplets": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary_chunks"] == 1
    assert body["decision_chunks"] == 1
    assert len(store.docs) == 2


def test_extract_rejects_bad_relation() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/sessions")
    app.state.storage_backend = FakeStore()
    app.state.project_root = ""
    r = TestClient(app).post(
        "/sessions/extract",
        json={
            "session_id": "s1",
            "summary": "x",
            "triplets": [{"subject": "a", "relation": "bogus", "object": "b"}],
        },
    )
    assert r.status_code == 422  # pydantic validation rejects closed-vocab break
