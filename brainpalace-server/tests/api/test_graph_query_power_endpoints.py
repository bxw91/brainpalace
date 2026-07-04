"""Plan E — path/impact/cochange endpoints (graph query power)."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import graph as graph_mod


def _app():
    sub = FastAPI()
    sub.include_router(graph_mod.router, prefix="/graph")
    return sub


def _client(mgr):
    return (
        patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", True),
        patch.object(graph_mod, "get_graph_store_manager", return_value=mgr),
    )


def test_path_resolves_ids_and_delegates():
    mgr = MagicMock()
    mgr.get_node.side_effect = lambda ref: {"id": ref} if ref in ("a", "b") else None
    mgr.find_paths.return_value = {"paths": [{"length": 1}], "nodes": []}
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/path?src=a&dst=b&max_depth=4&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["src"] == "a" and body["dst"] == "b"
    assert body["paths"] == [{"length": 1}]
    mgr.find_paths.assert_called_once_with("a", "b", max_depth=4, limit=2, domains=None)


def test_path_resolves_unique_name():
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = [{"id": "/p/a.py", "name": "a.py"}]
    mgr.find_paths.return_value = {"paths": [], "nodes": []}
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/path?src=a.py&dst=a.py")
    assert r.status_code == 200
    assert r.json()["src"] == "/p/a.py"


def test_ambiguous_name_is_400_with_candidates():
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = [{"id": "/p/a.py"}, {"id": "/q/a.py"}]
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/impact?node=a.py")
    assert r.status_code == 400
    assert "/p/a.py" in r.json()["detail"]


def test_ambiguous_name_lookup_uses_limit_5():
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = [{"id": "/p/a.py"}, {"id": "/q/a.py"}]
    p1, p2 = _client(mgr)
    with p1, p2:
        TestClient(_app()).get("/graph/impact?node=a.py")
    mgr.nodes_by_exact_name.assert_called_once_with("a.py", limit=5)


def test_ambiguous_name_at_limit_appends_ellipsis():
    # Exactly _AMBIGUITY_LOOKUP_LIMIT (5) candidates means more may exist
    # beyond the lookup cap — the message must not read as the full set.
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = [{"id": f"/p{i}/a.py"} for i in range(5)]
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/impact?node=a.py")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "…" in detail
    assert "/p0/a.py" in detail and "/p4/a.py" in detail


def test_ambiguous_name_below_limit_has_no_ellipsis():
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = [{"id": "/p/a.py"}, {"id": "/q/a.py"}]
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/impact?node=a.py")
    assert "…" not in r.json()["detail"]


def test_unknown_ref_is_404():
    mgr = MagicMock()
    mgr.get_node.return_value = None
    mgr.nodes_by_exact_name.return_value = []
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/cochange?node=zzz")
    assert r.status_code == 404


def test_impact_validates_predicates():
    mgr = MagicMock()
    mgr.get_node.side_effect = lambda ref: {"id": ref}
    mgr.impact.return_value = [{"id": "x", "depth": 1}]
    p1, p2 = _client(mgr)
    with p1, p2:
        c = TestClient(_app())
        ok = c.get("/graph/impact?node=n&predicates=calls,imports")
        bad = c.get("/graph/impact?node=n&predicates=frobnicates")
    assert ok.status_code == 200
    assert ok.json() == {"node": "n", "nodes": [{"id": "x", "depth": 1}]}
    mgr.impact.assert_called_once_with(
        "n", max_depth=3, predicates=["calls", "imports"], limit=200
    )
    assert bad.status_code == 400


def test_cochange_delegates():
    mgr = MagicMock()
    mgr.get_node.side_effect = lambda ref: {"id": ref}
    mgr.co_changed_files.return_value = [
        {"file_id": "/p/b.py", "name": "b.py", "shared_commits": 3}
    ]
    p1, p2 = _client(mgr)
    with p1, p2:
        r = TestClient(_app()).get("/graph/cochange?node=/p/a.py&min_shared=3&limit=5")
    assert r.status_code == 200
    assert r.json()["files"][0]["shared_commits"] == 3
    mgr.co_changed_files.assert_called_once_with("/p/a.py", min_shared=3, limit=5)


def test_disabled_graph_is_503():
    with patch.object(graph_mod.settings, "ENABLE_GRAPH_INDEX", False):
        r = TestClient(_app()).get("/graph/path?src=a&dst=b")
    assert r.status_code == 503
