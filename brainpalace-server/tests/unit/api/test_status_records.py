"""Task 14 — /status exposes a `records` block in the features dict."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.health import router


def _client(*, total: int, unverified: int, metrics: list[str]) -> TestClient:
    """Build a minimal test client with a mock RecordStore wired to app.state."""
    app = FastAPI()
    app.include_router(router)

    backend = MagicMock()
    backend.is_initialized = True

    async def _get_count(where=None):
        return 0

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
    indexing_service.get_document_count = AsyncMock(return_value=0)
    indexing_service.get_document_counts_by_type = AsyncMock(
        return_value={"code": 0, "doc": 0, "total": 0}
    )

    app.state.indexing_service = indexing_service
    app.state.storage_backend = backend
    app.state.job_service = None
    app.state.vector_store = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    app.state.file_watcher_service = SimpleNamespace(
        is_running=False, watched_folder_count=0
    )
    app.state.session_indexing_config = SimpleNamespace(
        enabled=False, archive=SimpleNamespace(retain_days=0)
    )
    app.state.session_index_enabled = False
    app.state.session_archive_enabled = False
    app.state.session_reconciler = SimpleNamespace(is_running=False)
    app.state.memory_service = SimpleNamespace(load=lambda: [])
    app.state.session_archive_service = None

    # Wire a mock RecordStore with the exact API used by the status assembler.
    mock_record_store = MagicMock()
    mock_record_store.record_count.return_value = total
    mock_record_store.count_unverified.return_value = unverified
    mock_record_store.distinct_metrics.return_value = metrics
    app.state.record_store = mock_record_store

    return TestClient(app)


def test_status_includes_records_block():
    client = _client(total=5, unverified=2, metrics=["sales"])
    data = client.get("/status").json()
    rb = data["features"]["records"]
    assert rb["total"] == 5
    assert rb["unverified"] == 2
    assert rb["metrics"] == ["sales"]
    assert "enabled" in rb
    assert "extraction_enabled" in rb


def test_status_records_absent_store_emits_zeros():
    """When record_store is None (e.g. SQLite failed to init), zeros are emitted."""
    app = FastAPI()
    app.include_router(router)

    backend = MagicMock()
    backend.is_initialized = True
    backend.get_count = AsyncMock(return_value=0)

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
    indexing_service.get_document_count = AsyncMock(return_value=0)
    indexing_service.get_document_counts_by_type = AsyncMock(
        return_value={"code": 0, "doc": 0, "total": 0}
    )

    app.state.indexing_service = indexing_service
    app.state.storage_backend = backend
    app.state.job_service = None
    app.state.vector_store = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    app.state.file_watcher_service = SimpleNamespace(
        is_running=False, watched_folder_count=0
    )
    app.state.session_indexing_config = SimpleNamespace(
        enabled=False, archive=SimpleNamespace(retain_days=0)
    )
    app.state.session_index_enabled = False
    app.state.session_archive_enabled = False
    app.state.session_reconciler = SimpleNamespace(is_running=False)
    app.state.memory_service = SimpleNamespace(load=lambda: [])
    app.state.session_archive_service = None
    app.state.record_store = None  # absent / init failed

    client = TestClient(app)
    data = client.get("/status").json()
    rb = data["features"]["records"]
    assert rb["total"] == 0
    assert rb["unverified"] == 0
    assert rb["metrics"] == []
    assert "enabled" in rb
    assert "extraction_enabled" in rb
