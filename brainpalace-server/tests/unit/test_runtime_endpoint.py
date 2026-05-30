"""Tests for the /runtime/ endpoint (B8)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server import __version__
from brainpalace_server.api.routers import runtime_router


def _make_app() -> FastAPI:
    """Build a minimal app exposing only the runtime router."""
    app = FastAPI()
    app.include_router(runtime_router, prefix="/runtime")
    return app


def test_runtime_returns_identity() -> None:
    """GET /runtime/ returns project_root, version, pid and started_at."""
    app = _make_app()
    app.state.project_root = "/home/dev/projects/demo"
    app.state.started_at = "2026-05-20T19:48:21+00:00"
    with TestClient(app) as client:
        resp = client.get("/runtime/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_root"] == "/home/dev/projects/demo"
    assert data["version"] == __version__
    assert isinstance(data["pid"], int) and data["pid"] > 0
    assert data["started_at"] == "2026-05-20T19:48:21+00:00"


def test_runtime_empty_when_state_unset() -> None:
    """GET /runtime/ returns empty strings when lifespan has not run."""
    app = _make_app()
    with TestClient(app) as client:
        resp = client.get("/runtime/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_root"] == ""
    assert data["started_at"] == ""
    assert data["version"] == __version__
