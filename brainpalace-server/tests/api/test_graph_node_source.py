"""Plan D Task 4 — lazy source-snippet endpoint for the detail panel."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import graph as graph_router


class _FakeMgr:
    def __init__(self, node):
        self._node = node

    def initialize(self) -> None:  # idempotent, matches the real manager
        pass

    def get_node(self, node_id):
        return self._node if self._node and self._node["id"] == node_id else None


def _client(monkeypatch, node) -> TestClient:
    app = FastAPI()
    app.include_router(graph_router.router, prefix="/graph")
    monkeypatch.setattr(graph_router, "get_graph_store_manager", lambda: _FakeMgr(node))
    monkeypatch.setattr(graph_router.settings, "ENABLE_GRAPH_INDEX", True)
    return TestClient(app)


def test_snippet_around_symbol(monkeypatch, tmp_path) -> None:
    src = tmp_path / "m.py"
    src.write_text("\n".join(f"line{i}" for i in range(50)))
    node = {
        "id": f"{src}:foo",
        "name": "foo",
        "label": "Function",
        "domain": "code",
        "properties": {"path": str(src), "line": 30, "character": 4},
    }
    r = _client(monkeypatch, node).get(
        "/graph/node/source", params={"node": node["id"], "context": 2}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == str(src)
    assert body["line"] == 30
    assert body["start_line"] == 28
    assert body["lines"] == ["line28", "line29", "line30", "line31", "line32"]


def test_file_node_uses_own_id_as_path(monkeypatch, tmp_path) -> None:
    src = tmp_path / "m.py"
    src.write_text("a\nb\nc\n")
    node = {
        "id": str(src),
        "name": "m.py",
        "label": "File",
        "domain": "code",
        "properties": {},
    }
    r = _client(monkeypatch, node).get("/graph/node/source", params={"node": str(src)})
    assert r.status_code == 200
    assert r.json()["start_line"] == 0


def test_non_code_file_node_never_serves_disk_path(monkeypatch, tmp_path) -> None:
    """Regression: an unresolved doc/session mention with object_type="File"
    becomes a non-code node whose id is an arbitrary absolute path (via
    POST /extraction/submit) — the File-id path fallback must only fire for
    domain='code' (indexer-created) nodes, else it serves that arbitrary path."""
    src = tmp_path / "secret.txt"
    src.write_text("a\nb\nc\n")
    node = {
        "id": str(src),
        "name": "secret.txt",
        "label": "File",
        "domain": "doc",
        "properties": {},
    }
    r = _client(monkeypatch, node).get("/graph/node/source", params={"node": str(src)})
    assert r.status_code == 404


def test_404s(monkeypatch, tmp_path) -> None:
    c = _client(monkeypatch, None)
    assert c.get("/graph/node/source", params={"node": "nope"}).status_code == 404

    gone = {
        "id": "x:foo",
        "name": "foo",
        "label": "Function",
        "domain": "code",
        "properties": {"path": str(tmp_path / "gone.py"), "line": 0},
    }
    c = _client(monkeypatch, gone)
    assert c.get("/graph/node/source", params={"node": "x:foo"}).status_code == 404

    noloc = {
        "id": "decorator:app.get",
        "name": "app.get",
        "label": "Decorator",
        "domain": "code",
        "properties": {},
    }
    c = _client(monkeypatch, noloc)
    assert (
        c.get("/graph/node/source", params={"node": "decorator:app.get"}).status_code
        == 404
    )
