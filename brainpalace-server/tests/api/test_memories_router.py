"""Memories router tests (Phase 030).

Keyless: a minimal FastAPI app with the router and a MemoryService whose
vector_store is None (markdown-only — sync/recall are no-ops). Exercises
routing, CRUD, and error codes without embeddings or the full app lifespan.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.memories import router
from brainpalace_server.services.memory_service import MemoryService


@pytest.fixture
def client(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/memories")
    app.state.memory_service = MemoryService(path=tmp_path / "BRAINPALACE_MEMORY.md")
    return TestClient(app)


def test_create_and_list(client):
    r = client.post("/memories/", json={"text": "staging url is staging.example.com",
                                        "section": "Environment", "tags": ["infra"]})
    assert r.status_code == 201, r.text
    mid = r.json()["memory"]["id"]
    assert mid.startswith("mem_")

    r = client.get("/memories/")
    body = r.json()
    assert body["total"] == 1
    assert body["memories"][0]["text"].startswith("staging url")
    assert body["char_count"] > 0 and body["char_cap"] > 0


def test_duplicate_409(client):
    client.post("/memories/", json={"text": "use Redis for cache"})
    r = client.post("/memories/", json={"text": "use Redis for cache"})
    assert r.status_code == 409


def test_list_filters_by_tag_and_section(client):
    client.post("/memories/", json={"text": "a", "section": "Environment",
                                     "tags": ["infra"]})
    client.post("/memories/", json={"text": "b", "section": "Decisions",
                                    "tags": ["arch"]})
    assert client.get("/memories/?tag=infra").json()["total"] == 1
    assert client.get("/memories/?section=Decisions").json()["total"] == 1


def test_delete_and_404(client):
    mid = client.post("/memories/", json={"text": "ephemeral"}).json()["memory"]["id"]
    assert client.delete(f"/memories/{mid}").status_code == 200
    assert client.get("/memories/").json()["total"] == 0
    assert client.delete("/memories/mem_nope").status_code == 404


def test_obsolete_excludes_from_default_list(client):
    mid = client.post("/memories/", json={"text": "temp fact"}).json()["memory"]["id"]
    r = client.post(f"/memories/{mid}/obsolete")
    assert r.status_code == 200
    assert client.get("/memories/").json()["total"] == 0
    assert client.get("/memories/?include_obsolete=true").json()["total"] == 1


def test_cap_413(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/memories")
    app.state.memory_service = MemoryService(path=tmp_path / "m.md", char_cap=300)
    c = TestClient(app)
    assert c.post("/memories/", json={"text": "small fact"}).status_code == 201
    assert c.post("/memories/", json={"text": "x" * 400}).status_code == 413


def test_recall_empty_without_index(client):
    client.post("/memories/", json={"text": "fact"})
    r = client.post("/memories/recall", json={"query": "fact"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_503_when_disabled():
    app = FastAPI()
    app.include_router(router, prefix="/memories")
    app.state.memory_service = None
    c = TestClient(app)
    assert c.get("/memories/").status_code == 503
