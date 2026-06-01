"""Phase 5.1 — /status exposes a consolidated per-feature block."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.health import router


def _client(*, session_enabled, session_running, curated, session_chunks):
    app = FastAPI()
    app.include_router(router)

    backend = MagicMock()
    backend.is_initialized = True

    async def _get_count(where=None):
        if where and where.get("source_type") == "session_turn":
            return session_chunks
        return 42  # total_chunks

    backend.get_count = AsyncMock(side_effect=_get_count)

    indexing_service = MagicMock()
    indexing_service.get_status = AsyncMock(
        return_value={
            "status": "idle",
            "total_doc_chunks": 0,
            "total_code_chunks": 0,
            "indexed_folders": [],
            "supported_languages": [],
            "graph_index": {"enabled": False},
            "completed_at": None,
        }
    )
    indexing_service.get_document_count = AsyncMock(return_value=3)

    app.state.indexing_service = indexing_service
    app.state.storage_backend = backend
    app.state.job_service = None
    app.state.vector_store = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    # health.py reads file_watcher_service (.is_running / .watched_folder_count).
    app.state.file_watcher_service = SimpleNamespace(
        is_running=True, watched_folder_count=2
    )
    app.state.session_indexing_config = SimpleNamespace(enabled=session_enabled)
    app.state.session_watcher = SimpleNamespace(is_running=session_running)
    app.state.memory_service = SimpleNamespace(load=lambda: [object()] * curated)
    return TestClient(app)


def test_status_reports_feature_block():
    client = _client(
        session_enabled=True, session_running=True, curated=5, session_chunks=7
    )
    feats = client.get("/status").json()["features"]

    assert feats["doc_indexing"]["active"] is True
    assert feats["doc_indexing"]["total_chunks"] == 42
    assert feats["doc_indexing"]["total_documents"] == 3
    assert feats["file_watcher"]["enabled"] is True
    assert feats["file_watcher"]["watched_folders"] == 2
    assert feats["session_memory"]["enabled"] is True
    assert feats["session_memory"]["watcher_running"] is True
    assert feats["session_memory"]["session_chunks"] == 7
    assert feats["session_memory"]["curated_memories"] == 5
    assert feats["graph_index"]["enabled"] is False


def test_status_feature_block_session_disabled():
    client = _client(
        session_enabled=False, session_running=False, curated=0, session_chunks=0
    )
    feats = client.get("/status").json()["features"]
    assert feats["session_memory"]["enabled"] is False
    assert feats["session_memory"]["watcher_running"] is False
