from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.main import _install_quarantine_middleware
from brainpalace_server.rehome.quarantine import QuarantineState


def _mk_app(active: bool):
    app = FastAPI()
    _install_quarantine_middleware(app)

    @app.get("/query/ping")
    async def _q():  # a non-allowlisted route
        return {"ok": True}

    @app.get("/health/ping")
    async def _h():  # allowlisted
        return {"ok": True}

    app.state.rehome_quarantine = QuarantineState(
        active=active, reason="rehome pending"
    )
    return app


def test_quarantine_blocks_normal_route_503():
    app = _mk_app(active=True)
    c = TestClient(app)
    blocked = c.get("/query/ping")
    allowed = c.get("/health/ping")
    assert blocked.status_code == 503
    assert "rehome" in blocked.json()["detail"].lower()
    assert allowed.status_code == 200


def test_no_quarantine_passes_through():
    app = _mk_app(active=False)
    c = TestClient(app)
    r = c.get("/query/ping")
    assert r.status_code == 200
