"""Session archive/decision/timeline endpoints (dashboard plan 05)."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import sessions as sessions_mod


class FakeArchive:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def iter_sessions(self):
        yield "sid-1", self.base_dir / "does-not-exist-1.jsonl", 100.0
        yield "sid-2", self.base_dir / "does-not-exist-2.jsonl", 200.0

    def stats(self):
        return {
            "archived_sessions": 2,
            "archived_files": 3,
            "tombstoned": 0,
            "archived_bytes": 999,
        }


def _app(archive=None):
    sub = FastAPI()
    sub.include_router(sessions_mod.router, prefix="/sessions")
    sub.state.session_archive_service = archive
    return sub


def test_archive_lists_sessions_newest_first(tmp_path):
    c = TestClient(_app(FakeArchive(tmp_path)))
    r = c.get("/sessions/archive")
    assert r.status_code == 200
    body = r.json()
    assert [s["session_id"] for s in body["sessions"]] == ["sid-2", "sid-1"]
    assert body["archived_files"] == 3
    # Missing files report size 0 instead of erroring.
    assert body["sessions"][0]["size_bytes"] == 0


def test_archive_503_when_disabled():
    c = TestClient(_app(None))
    assert c.get("/sessions/archive").status_code == 503


def test_decisions_lists_from_graph(tmp_path):
    mgr = MagicMock()
    mgr.nodes_by_label.return_value = [
        {"id": "d1", "name": "use poetry", "label": "Decision"}
    ]
    with patch.object(sessions_mod, "get_graph_store_manager", return_value=mgr):
        c = TestClient(_app(FakeArchive(tmp_path)))
        r = c.get("/sessions/decisions?contains=poetry&limit=5")
    assert r.status_code == 200
    assert r.json()["decisions"][0]["name"] == "use poetry"
    # Cold-start: the endpoint must initialize the (idempotent) graph store
    # before reading, or a freshly restarted server silently returns [].
    mgr.initialize.assert_called_once()
    mgr.nodes_by_label.assert_called_once_with("Decision", contains="poetry", limit=5)


def test_decisions_rejects_out_of_range_limit(tmp_path):
    # Validation rejects before the handler runs — no graph patch needed.
    c = TestClient(_app(FakeArchive(tmp_path)))
    assert c.get("/sessions/decisions?limit=0").status_code == 422


def test_timeline_returns_rows(tmp_path):
    mgr = MagicMock()
    mgr.timeline_named.return_value = [
        {
            "subject": "use uv",
            "predicate": "supersedes",
            "object": "use poetry",
            "valid_from": "2026-03-01T00:00:00",
            "valid_until": None,
            "valid": True,
        }
    ]
    with patch.object(sessions_mod, "get_graph_store_manager", return_value=mgr):
        c = TestClient(_app(FakeArchive(tmp_path)))
        r = c.get("/sessions/timeline", params={"entity": "use poetry"})
    assert r.status_code == 200
    assert r.json()["timeline"][0]["predicate"] == "supersedes"
    # Cold-start: see test_decisions_lists_from_graph.
    mgr.initialize.assert_called_once()
