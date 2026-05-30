"""Context router tests (Phase 035). Keyless minimal app."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.context import router
from brainpalace_server.services.memory_service import MemoryService
from brainpalace_server.services.session_context_service import SessionContextService


@pytest.fixture
def app_with(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/context")
    mem = MemoryService(path=tmp_path / "BRAINPALACE_MEMORY.md")
    app.state.memory_service = mem
    app.state.session_context_service = SessionContextService(memory_service=mem)
    app.state.project_root = str(tmp_path)
    app.state.query_service = None  # no index; doc_count omitted
    return app, mem


def test_session_start_returns_block(app_with):
    app, _ = app_with
    c = TestClient(app)
    r = c.get("/context/session-start")
    assert r.status_code == 200
    body = r.json()
    assert "project_facts" in body["sections"]
    assert body["text"].startswith("# BrainPalace")
    assert body["token_estimate"] > 0


def test_session_start_includes_memory(app_with, tmp_path):
    app, mem = app_with
    import asyncio

    asyncio.run(mem.add("staging url is x", section="Environment"))
    c = TestClient(app)
    body = c.get("/context/session-start").json()
    assert "memory" in body["sections"]
    assert "staging url is x" in body["text"]


def test_503_when_disabled():
    app = FastAPI()
    app.include_router(router, prefix="/context")
    app.state.session_context_service = None
    c = TestClient(app)
    assert c.get("/context/session-start").status_code == 503
