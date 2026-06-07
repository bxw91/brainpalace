import httpx
import pytest

import brainpalace_dashboard.services.proxy as proxy_mod
from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr(
        proxy_mod,
        "instance_base_url",
        lambda id_: "http://server.test",
    )
    return ProxyService()


async def test_request_returns_json(svc):
    def handler(request):
        assert request.url.path == "/health/status"
        return httpx.Response(200, json={"total_chunks": 42})

    transport = httpx.MockTransport(handler)
    svc._client = httpx.AsyncClient(transport=transport)
    out = await svc.request("abc", "GET", "/health/status")
    assert out["total_chunks"] == 42


async def test_request_normalizes_upstream_error(svc):
    def handler(request):
        return httpx.Response(503, json={"detail": "Index not ready"})

    svc._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError) as ei:
        await svc.request("abc", "GET", "/health/status")
    assert ei.value.upstream_status == 503
    assert "not ready" in ei.value.detail.lower()


async def test_request_raises_when_no_base_url(monkeypatch):
    monkeypatch.setattr(proxy_mod, "instance_base_url", lambda id_: "")
    svc = ProxyService()
    with pytest.raises(UpstreamError) as ei:
        await svc.request("abc", "GET", "/health/status")
    assert ei.value.upstream_status == 502
