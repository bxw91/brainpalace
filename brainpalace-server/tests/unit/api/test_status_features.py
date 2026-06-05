"""Phase 5.1 — /status exposes a consolidated per-feature block."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.health import router


def _client(
    *,
    session_enabled,
    session_running,
    curated,
    session_chunks,
    archive_stats=None,
    archive_enabled=None,
):
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
    indexing_service.get_document_counts_by_type = AsyncMock(
        return_value={"code": 2, "doc": 1, "total": 3}
    )

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
    app.state.session_indexing_config = SimpleNamespace(
        enabled=session_enabled, archive=SimpleNamespace(retain_days=0)
    )
    # Resolved capability flags (archive + index independent).
    app.state.session_index_enabled = session_enabled
    app.state.session_archive_enabled = (
        session_enabled if archive_enabled is None else archive_enabled
    )
    app.state.session_reconciler = SimpleNamespace(is_running=session_running)
    app.state.memory_service = SimpleNamespace(load=lambda: [object()] * curated)
    if archive_stats is None:
        app.state.session_archive_service = None
    else:
        app.state.session_archive_service = SimpleNamespace(stats=lambda: archive_stats)
    return TestClient(app)


def test_status_reports_feature_block():
    client = _client(
        session_enabled=True, session_running=True, curated=5, session_chunks=7
    )
    data = client.get("/status").json()
    # Code/doc split from get_document_counts_by_type propagates to the response.
    assert data["total_documents"] == 3
    assert data["code_documents"] == 2
    assert data["doc_documents"] == 1
    feats = data["features"]

    assert feats["doc_indexing"]["active"] is True
    assert feats["doc_indexing"]["total_chunks"] == 42
    assert feats["doc_indexing"]["total_documents"] == 3
    assert feats["file_watcher"]["enabled"] is True
    assert feats["file_watcher"]["watched_folders"] == 2
    assert feats["session_memory"]["enabled"] is True
    assert feats["session_memory"]["watcher_running"] is True
    assert feats["session_memory"]["session_chunks"] == 7
    assert feats["session_memory"]["curated_memories"] == 5
    assert feats["session_memory"]["archived_sessions"] == 0
    assert feats["session_memory"]["archived_bytes"] == 0
    assert feats["session_memory"]["tombstoned"] == 0
    # Archive is its own independent feature block.
    assert feats["session_archive"]["enabled"] is True
    assert feats["session_archive"]["retain_days"] == 0
    assert feats["graph_index"]["enabled"] is False


def test_status_feature_block_session_disabled():
    client = _client(
        session_enabled=False, session_running=False, curated=0, session_chunks=0
    )
    feats = client.get("/status").json()["features"]
    assert feats["session_memory"]["enabled"] is False
    assert feats["session_memory"]["watcher_running"] is False


def test_archive_on_index_off_independent():
    # Existing-project shape: archive ON, index OFF — independent feature rows.
    client = _client(
        session_enabled=False,
        session_running=False,
        curated=0,
        session_chunks=0,
        archive_enabled=True,
        archive_stats={
            "archived_sessions": 4,
            "archived_files": 5,
            "archived_bytes": 999,
            "tombstoned": 0,
        },
    )
    feats = client.get("/status").json()["features"]
    assert feats["session_memory"]["enabled"] is False
    assert feats["session_archive"]["enabled"] is True
    assert feats["session_archive"]["archived_files"] == 5


def test_session_memory_includes_archive_counts():
    client = _client(
        session_enabled=True,
        session_running=True,
        curated=0,
        session_chunks=2,
        archive_stats={
            "archived_sessions": 2,
            "archived_files": 3,
            "archived_bytes": 1234,
            "tombstoned": 1,
        },
    )
    sm = client.get("/status").json()["features"]["session_memory"]
    assert sm["archived_sessions"] == 2
    assert sm["archived_files"] == 3
    assert sm["archived_bytes"] == 1234
    assert sm["tombstoned"] == 1
