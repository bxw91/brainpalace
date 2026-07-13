from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.rehome import router as rehome_router
from brainpalace_server.rehome.quarantine import QuarantineState


def _app_with_state(**state):
    app = FastAPI()
    app.include_router(rehome_router, prefix="/rehome")
    for k, v in state.items():
        setattr(app.state, k, v)
    return app


def test_status_reports_quarantine():
    app = _app_with_state(
        rehome_quarantine=QuarantineState(
            active=True, reason="pending", status="failed"
        ),
        state_dir_str="/x",
    )
    c = TestClient(app)
    r = c.get("/rehome/")
    assert r.status_code == 200
    body = r.json()
    assert body["quarantined"] is True
    assert body["status"] == "failed"
    assert "pending" in (body["reason"] or "")


def test_status_not_quarantined():
    app = _app_with_state(
        rehome_quarantine=QuarantineState(active=False), state_dir_str="/x"
    )
    c = TestClient(app)
    r = c.get("/rehome/")
    assert r.status_code == 200
    assert r.json()["quarantined"] is False


def test_resume_without_pending_returns_409():
    # Not quarantined -> nothing to resume.
    app = _app_with_state(
        rehome_quarantine=QuarantineState(active=False), state_dir_str="/x"
    )
    c = TestClient(app)
    r = c.post("/rehome/resume")
    assert r.status_code == 409
