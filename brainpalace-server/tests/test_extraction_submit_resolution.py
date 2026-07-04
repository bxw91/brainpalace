"""Plan B Task 5 — doc submit resolves mentions onto code nodes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.extraction import router
from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import GraphStoreManager


class FakePendingStore:
    def __init__(self) -> None:
        self.done: list[str] = []

    def get_text(self, chunk_id: str) -> str | None:
        return "some pending text"

    def mark_done(self, chunk_id: str) -> None:
        self.done.append(chunk_id)


@pytest.fixture(autouse=True)
def _graph(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    mgr = GraphStoreManager.get_instance(
        persist_dir=tmp_path / "graph_index", store_type="sqlite"
    )
    mgr.initialize()
    # Seed the canonical code File node the doc mention should land on.
    mgr.add_triplet(
        "auth.py",
        "defined_in",
        "auth.py",
        subject_id="/repo/src/auth.py:login",
        object_id="/repo/src/auth.py",
        subject_name="login",
        object_name="auth.py",
        subject_type="Function",
        object_type="File",
    )
    yield mgr
    GraphStoreManager.reset_instance()


@pytest.fixture()
def client(_graph) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    app.state.doc_pending_store = FakePendingStore()
    app.state.project_root = "/repo"
    return TestClient(app)


def test_doc_submit_links_resolved_object(client: TestClient, _graph) -> None:
    resp = client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": "chunk_x",
            "triplets": [
                {
                    "subject": "Auth design",
                    "predicate": "references",
                    "object": "src/auth.py",
                    "subject_type": "DesignDoc",
                    "object_type": "File",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["triplets_stored"] == 1
    store = _graph.graph_store
    row = store._conn.execute(
        "SELECT target_id, properties FROM edges WHERE label = 'references'"
    ).fetchone()
    assert row["target_id"] == "/repo/src/auth.py"
    assert '"resolved": true' in row["properties"]
    node = store._conn.execute(
        "SELECT domain FROM nodes WHERE id = '/repo/src/auth.py'"
    ).fetchone()
    assert node["domain"] == "code"  # the doc write must not flip it


def test_doc_submit_unresolved_unchanged(client: TestClient, _graph) -> None:
    resp = client.post(
        "/extraction/submit",
        json={
            "source": "doc",
            "chunk_id": "chunk_y",
            "triplets": [
                {
                    "subject": "Idea",
                    "predicate": "references",
                    "object": "some concept",
                }
            ],
        },
    )
    assert resp.status_code == 200
    store = _graph.graph_store
    node = store._conn.execute(
        "SELECT domain FROM nodes WHERE name = 'some concept'"
    ).fetchone()
    assert node["domain"] == "doc"
