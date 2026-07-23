from fastapi.testclient import TestClient

import brainpalace_dashboard.api.routes_data as rd
from brainpalace_dashboard.app import create_app


class FakeProxy:
    def __init__(self):
        self.calls = []

    async def request(self, id_, method, path, json=None, params=None):
        self.calls.append((method, path, json, params))
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


def test_metrics_usage_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/metrics/usage?window=7d")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/metrics/usage")
    assert call[0] == "GET" and call[3] == {"window": "7d"}


def test_metrics_usage_proxy_default_window(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/metrics/usage")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/metrics/usage")
    assert call[3] == {"window": "24h"}


def test_graph_top_proxy(monkeypatch):
    """The /graph/top hub-seed route must proxy to the server (regression: it
    was missing, so the request fell through to the SPA and returned HTML)."""
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/graph/top?limit=5")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/graph/top")
    assert call[0] == "GET" and call[3] == {"limit": 5}


def test_graph_top_proxy_default_limit(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/graph/top")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/graph/top")
    assert call[3] == {"limit": 20}


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


def test_remove_folder_normalizes_path_key(monkeypatch):
    # Older frontend builds sent {"path": ...}; the server contract is
    # {"folder_path": ...}. The proxy must forward folder_path so removal
    # doesn't 422 regardless of the bundled asset version.
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.request(
        "DELETE", "/dashboard/api/instances/abc/folders", json={"path": "/p"}
    )
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[0] == "DELETE" and c[1] == "/index/folders/")
    assert call[2].get("folder_path") == "/p"


def test_remove_folder_passes_folder_path_through(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.request(
        "DELETE", "/dashboard/api/instances/abc/folders", json={"folder_path": "/p"}
    )
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[0] == "DELETE" and c[1] == "/index/folders/")
    assert call[2].get("folder_path") == "/p"


def test_jobs_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/jobs")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[:2] == ("GET", "/index/jobs/"))
    assert call[3] is None  # no ?all param -> no-op jobs hidden by default


def test_jobs_proxy_all_true_forwards_all_param(monkeypatch):
    """Fix 4 (A7): ?all=1 on the dashboard route forwards ?all=1 to the server
    so the "show no-op runs" toggle reveals them."""
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/jobs?all=1")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[:2] == ("GET", "/index/jobs/"))
    assert call[3] == {"all": 1}


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
    assert call[3] == {"lines": 50, "level": "ERROR"}


def test_logs_proxy_default_lines(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/logs")
    assert resp.status_code == 200
    call = next(c for c in fp.calls if c[1] == "/health/logs")
    # no level key when level not supplied
    assert call[3] == {"lines": 200}


def test_documents_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get(
        "/dashboard/api/instances/abc/documents",
        params={"folder": "/proj", "contains": "py", "limit": 10, "offset": 0},
    )
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/index/documents")
    assert params["folder"] == "/proj"
    assert params["contains"] == "py"


def test_document_chunks_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get(
        "/dashboard/api/instances/abc/documents/chunks",
        params={"folder": "/proj", "path": "/proj/a.py", "limit": 20},
    )
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/index/documents/chunks")
    assert params["path"] == "/proj/a.py"


def test_ingest_sources_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get(
        "/dashboard/api/instances/abc/ingest/sources",
        params={"domain": "home", "include_sensitive": True},
    )
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/ingest/sources")
    assert params["domain"] == "home"
    assert params["include_sensitive"] is True


def test_ingest_chunks_proxies_to_source_path(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get(
        "/dashboard/api/instances/abc/ingest/chunks",
        params={"source_id": "email-2024", "offset": 100, "limit": 50},
    )
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/ingest/text/email-2024")
    assert params["offset"] == 100
    assert params["limit"] == 50


def test_cache_history_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/cache/history?since=1.5")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/index/cache/history")
    assert params == {"since": 1.5}


def test_cache_economics_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/cache/economics?avg_tokens=500")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/index/cache/economics")
    assert params == {"avg_tokens": 500}


def test_sessions_archive_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/sessions/archive")
    method, path, _json, _params = fake.calls[-1]
    assert (method, path) == ("GET", "/sessions/archive")


def test_sessions_decisions_and_timeline_proxy(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/sessions/decisions?contains=x&limit=5")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/sessions/decisions")
    assert params == {"contains": "x", "limit": 5}
    c.get("/dashboard/api/instances/abc/sessions/timeline?entity=use%20poetry")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/sessions/timeline")
    assert params == {"entity": "use poetry"}


def test_memory_create_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.post(
        "/dashboard/api/instances/abc/memories",
        json={"text": "prefer uv", "section": "tooling"},
    )
    method, path, body, _params = fake.calls[-1]
    assert (method, path) == ("POST", "/memories/")
    assert body["text"] == "prefer uv"


def test_graph_nodes_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/graph/nodes?q=query&limit=10")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/graph/nodes")
    assert params == {"q": "query", "limit": 10}


def test_graph_neighbors_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.get("/dashboard/api/instances/abc/graph/neighbors?node=n1")
    method, path, _json, params = fake.calls[-1]
    assert (method, path) == ("GET", "/graph/neighbors")
    assert params == {"node": "n1", "limit": 200}


def test_providers_test_proxies(monkeypatch):
    fake = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fake)
    c = TestClient(create_app())
    c.post("/dashboard/api/instances/abc/providers/test")
    method, path, _json, _params = fake.calls[-1]
    assert (method, path) == ("POST", "/health/providers/test")


def test_upstream_error_normalized(monkeypatch):
    monkeypatch.setattr(rd, "proxy", ErrorProxy())
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/status")
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"] == "upstream"
    assert body["upstream_status"] == 502
    assert "running" in body["detail"]
