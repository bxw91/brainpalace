from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_data as rd
from brainpalace_dashboard.app import create_app


class FakeProxy:
    def __init__(self):
        self.calls = []

    async def request(self, id_, method, path, json=None, params=None):
        self.calls.append((method, path, params))
        if path == "/health/status":
            return {"total_chunks": 9}
        if path == "/index/folders/":
            return {"folders": []}
        if path == "/index/cache/":
            return {"hit_rate": 0.9}
        if path == "/health/logs":
            return {"lines": ["line a", "line b"]}
        return {"ok": True}


class ErrorProxy:
    """Always raises an UpstreamError (stopped instance / 502)."""

    async def request(self, id_, method, path, json=None, params=None):
        from brainpalace_dashboard.services.proxy import UpstreamError

        raise UpstreamError("instance not running or unknown", 502)


def test_status_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/status")
    assert resp.json()["total_chunks"] == 9
    assert any(c[:2] == ("GET", "/health/status") for c in fp.calls)


def test_clear_cache_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.delete("/dashboard/api/instances/abc/cache")
    assert resp.status_code == 200
    assert any(c[:2] == ("DELETE", "/index/cache/") for c in fp.calls)


def test_folders_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/folders")
    assert resp.status_code == 200
    assert any(c[:2] == ("GET", "/index/folders/") for c in fp.calls)


def test_jobs_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/jobs")
    assert resp.status_code == 200
    assert any(c[:2] == ("GET", "/index/jobs/") for c in fp.calls)


def test_capabilities_proxy(monkeypatch):
    class CapsProxy:
        async def request(self, id_, method, path, json=None, params=None):
            assert path == "/openapi.json"
            return {
                "paths": {
                    "/health/status": {"get": {"summary": "S", "tags": ["health"]}}
                }
            }

    monkeypatch.setattr(rd, "proxy", CapsProxy())
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/capabilities")
    assert resp.status_code == 200
    caps = resp.json()
    assert any(c["path"] == "/health/status" for c in caps)


def test_logs_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/logs?lines=50&level=ERROR")
    assert resp.status_code == 200
    assert resp.json()["lines"] == ["line a", "line b"]
    # forwarded to the server /health/logs with the params
    call = next(c for c in fp.calls if c[1] == "/health/logs")
    assert call[0] == "GET"
    assert call[2] == {"lines": 50, "level": "ERROR"}


def test_logs_proxy_default_lines(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/logs")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/health/logs")
    # no level key when level not supplied
    assert call[2] == {"lines": 200}


def test_upstream_error_normalized(monkeypatch):
    monkeypatch.setattr(rd, "proxy", ErrorProxy())
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/status")
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"] == "upstream"
    assert body["upstream_status"] == 502
    assert "running" in body["detail"]
