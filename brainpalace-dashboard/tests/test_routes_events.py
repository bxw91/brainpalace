import json

import pytest
from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_events as re
from brainpalace_dashboard.app import create_app


@pytest.fixture(autouse=True)
def _reset_sse_exit_event():
    """sse-starlette keeps a process-global ``should_exit_event`` bound to the
    loop of the first request; a second TestClient runs on a fresh loop and the
    stale event raises ``bound to a different event loop``. Reset it per test so
    each stream re-creates the event on its own loop."""
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


class FakeService:
    def list(self):
        return [
            {"id": "a", "name": "alpha", "status": "running"},
            {"id": "b", "name": "beta", "status": "stopped"},
        ]


def test_events_stream_emits_instances(monkeypatch):
    monkeypatch.setattr(re, "service", FakeService())
    client = TestClient(create_app())
    # max_ticks bounds the stream so the request terminates for the test.
    resp = client.get("/dashboard/api/events?max_ticks=1&poll_s=0")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: instances" in body
    # Pull the data line and confirm it carries the fleet payload.
    data_line = next(line for line in body.splitlines() if line.startswith("data:"))
    payload = json.loads(data_line[len("data:") :].strip())
    assert any(row["id"] == "a" for row in payload)


def test_events_stream_respects_max_ticks(monkeypatch):
    monkeypatch.setattr(re, "service", FakeService())
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/events?max_ticks=2&poll_s=0")
    assert resp.text.count("event: instances") == 2
