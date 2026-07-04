"""Plan E — manager wrappers for path/impact reads."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from brainpalace_server.storage.graph_store import GraphStoreManager


def _manager_with(store) -> GraphStoreManager:
    mgr = GraphStoreManager(Path("/tmp/unused"), store_type="sqlite")
    mgr._graph_store = store
    mgr._initialized = True
    return mgr


def test_find_paths_delegates():
    store = MagicMock()
    store.find_paths.return_value = {"paths": [{"length": 1}], "nodes": []}
    mgr = _manager_with(store)
    with patch("brainpalace_server.storage.graph_store.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        out = mgr.find_paths("a", "b", max_depth=4, limit=2, domains=["code"])
    assert out["paths"] == [{"length": 1}]
    store.find_paths.assert_called_once_with(
        "a", "b", max_depth=4, limit=2, domains=["code"]
    )


def test_impact_delegates():
    store = MagicMock()
    store.impact.return_value = [{"id": "x", "depth": 1}]
    mgr = _manager_with(store)
    with patch("brainpalace_server.storage.graph_store.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        out = mgr.impact("a", max_depth=2, predicates=["calls"], limit=10)
    assert out == [{"id": "x", "depth": 1}]
    store.impact.assert_called_once_with(
        "a", max_depth=2, predicates=["calls"], limit=10
    )


def test_unsupported_backend_degrades_to_empty():
    class Bare:  # no find_paths / impact (simple backend)
        pass

    mgr = _manager_with(Bare())
    with patch("brainpalace_server.storage.graph_store.settings") as s:
        s.ENABLE_GRAPH_INDEX = True
        assert mgr.find_paths("a", "b") == {"paths": [], "nodes": []}
        assert mgr.impact("a") == []


def test_disabled_degrades_to_empty():
    mgr = _manager_with(MagicMock())
    with patch("brainpalace_server.storage.graph_store.settings") as s:
        s.ENABLE_GRAPH_INDEX = False
        assert mgr.find_paths("a", "b") == {"paths": [], "nodes": []}
        assert mgr.impact("a") == []
