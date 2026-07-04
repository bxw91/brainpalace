"""Graph browse endpoints (dashboard plan 06)."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import graph as graph_mod


def _app():
    sub = FastAPI()
    sub.include_router(graph_mod.router, prefix="/graph")
    return sub


def test_nodes_search():
    mgr = MagicMock()
    mgr.search_nodes.return_value = [
        {"id": "n1", "name": "QueryService", "label": "Class", "degree": 3}
    ]
    with (
        patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", True),
        patch.object(graph_mod, "get_graph_store_manager", return_value=mgr),
    ):
        c = TestClient(_app())
        r = c.get("/graph/nodes?q=query&limit=10")
    assert r.status_code == 200
    assert r.json()["nodes"][0]["name"] == "QueryService"
    mgr.search_nodes.assert_called_once_with("query", limit=10, domains=None)


def test_neighbors():
    mgr = MagicMock()
    mgr.neighbors.return_value = {
        "nodes": [{"id": "n1", "name": "a", "label": "Class"}],
        "edges": [],
    }
    with (
        patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", True),
        patch.object(graph_mod, "get_graph_store_manager", return_value=mgr),
    ):
        c = TestClient(_app())
        r = c.get("/graph/neighbors?node=n1&limit=100")
    assert r.status_code == 200
    assert r.json()["nodes"][0]["id"] == "n1"
    mgr.neighbors.assert_called_once_with(["n1"], limit=100, domains=None)


def test_top_nodes():
    mgr = MagicMock()
    mgr.top_nodes.return_value = [
        {"id": "n1", "name": "QueryService", "label": "Class", "degree": 9}
    ]
    with (
        patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", True),
        patch.object(graph_mod, "get_graph_store_manager", return_value=mgr),
    ):
        c = TestClient(_app())
        r = c.get("/graph/top?limit=15")
    assert r.status_code == 200
    assert r.json()["nodes"][0]["degree"] == 9
    mgr.top_nodes.assert_called_once_with(limit=15, domains=None)


def test_endpoints_initialize_store_before_reading():
    """Regression: browse endpoints must initialize the (lazily-loaded) store.

    Counts come from the ``graph_metadata.json`` sidecar without loading the
    store, so on a freshly started server ``_graph_store`` stays ``None`` and
    every browse query returns empty even though entities exist on disk. The
    endpoints must call ``mgr.initialize()`` (idempotent) first.
    """
    mgr = MagicMock()
    mgr.top_nodes.return_value = []
    mgr.search_nodes.return_value = []
    mgr.neighbors.return_value = {"nodes": [], "edges": []}
    with (
        patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", True),
        patch.object(graph_mod, "get_graph_store_manager", return_value=mgr),
    ):
        c = TestClient(_app())
        c.get("/graph/top?limit=5")
        c.get("/graph/nodes?q=x&limit=5")
        c.get("/graph/neighbors?node=n1&limit=5")
    assert mgr.initialize.call_count == 3


def test_503_when_graph_disabled():
    with patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", False):
        c = TestClient(_app())
        assert c.get("/graph/nodes?q=x").status_code == 503
        assert c.get("/graph/top").status_code == 503
        assert c.get("/graph/neighbors?node=n1").status_code == 503
