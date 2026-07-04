"""Regression tests for POST /index/?rebuild_graph=true (BM25 API drift).

The endpoint once accessed ``bm25_manager._index.nodes`` — a leftover of the
legacy LlamaIndex ``BM25Retriever`` shape — and crashed with
``'BM25IndexManager' object has no attribute '_index'``. Plan 4 Task 6
delegated the rebuild body to ``IndexingService.rebuild_graph_from_corpus``
(shared with the Step-6 auto-trigger), so these tests now pin the router's
delegation contract (correct args, response shape, gating) at that boundary
instead of asserting the old inline BM25/graph_mgr calls directly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import index as index_mod


def _app(indexing_service: MagicMock) -> FastAPI:
    sub = FastAPI()
    sub.include_router(index_mod.router, prefix="/index")
    sub.state.indexing_service = indexing_service
    return sub


def _service(triplet_count: int) -> MagicMock:
    service = MagicMock()
    service.vector_store.is_initialized = True
    service.rebuild_graph_from_corpus = AsyncMock(return_value=triplet_count)
    return service


def test_rebuild_graph_delegates_to_service():
    service = _service(triplet_count=3)

    with patch.object(index_mod.settings, "ENABLE_GRAPH_INDEX", True):
        client = TestClient(_app(service))
        response = client.post("/index/?rebuild_graph=true", json={"folder_path": "."})

    assert response.status_code == 202, response.json()
    data = response.json()
    assert data["job_id"] == "rebuild_graph"
    assert data["status"] == "completed"
    assert "3" in data["message"]
    service.rebuild_graph_from_corpus.assert_called_once_with(".")


def test_rebuild_graph_empty_corpus_returns_400():
    service = _service(triplet_count=0)

    with patch.object(index_mod.settings, "ENABLE_GRAPH_INDEX", True):
        client = TestClient(_app(service))
        response = client.post("/index/?rebuild_graph=true", json={"folder_path": "."})

    assert response.status_code == 400
    assert "No documents indexed" in response.json()["detail"]


def test_rebuild_graph_vector_store_not_initialized_returns_400():
    service = _service(triplet_count=3)
    service.vector_store.is_initialized = False

    with patch.object(index_mod.settings, "ENABLE_GRAPH_INDEX", True):
        client = TestClient(_app(service))
        response = client.post("/index/?rebuild_graph=true", json={"folder_path": "."})

    assert response.status_code == 400
    assert "No documents indexed" in response.json()["detail"]
    service.rebuild_graph_from_corpus.assert_not_called()


def test_rebuild_graph_disabled_returns_400():
    service = _service(triplet_count=0)

    with patch.object(index_mod.settings, "ENABLE_GRAPH_INDEX", False):
        client = TestClient(_app(service))
        response = client.post("/index/?rebuild_graph=true", json={"folder_path": "."})

    assert response.status_code == 400
    assert "ENABLE_GRAPH_INDEX" in response.json()["detail"]
