"""DocServeClient rehome_status / rehome_resume."""

import httpx
import pytest

from brainpalace_cli.client.api_client import DocServeClient, ServerError


def _client_with(handler):
    c = DocServeClient(base_url="http://t")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_rehome_status_get():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/rehome/"
        return httpx.Response(
            200, json={"quarantined": True, "status": "failed", "reason": "boom"}
        )

    data = _client_with(handler).rehome_status()
    assert data["quarantined"] is True
    assert data["status"] == "failed"


def test_rehome_resume_post():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/rehome/resume"
        return httpx.Response(
            200,
            json={
                "quarantined": False,
                "status": "done",
                "resumed_workers": ["job_worker"],
            },
        )

    data = _client_with(handler).rehome_resume()
    assert data["status"] == "done"
    assert data["resumed_workers"] == ["job_worker"]


def test_rehome_resume_409_raises_servererror():
    def handler(request):
        return httpx.Response(409, json={"detail": "no pending rehome to resume"})

    with pytest.raises(ServerError) as ei:
        _client_with(handler).rehome_resume()
    assert ei.value.status_code == 409
