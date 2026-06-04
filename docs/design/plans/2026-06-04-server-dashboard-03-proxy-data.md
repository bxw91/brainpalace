# Dashboard Plan 03 — ProxyService + capabilities + per-instance data/action endpoints

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–02.

**Goal:** Proxy each project server's REST API (status, folders, jobs, cache, providers, graph, sessions, memories) through normalized control-plane endpoints, plus a capabilities endpoint that parses the server's OpenAPI.

**Architecture:** `ProxyService` holds an async httpx client; given an instance id it looks up `base_url` via `InstanceService`, calls the upstream path, and normalizes errors to `{error, detail, upstream_status}`. `routes_data.py` exposes thin GET/POST/DELETE wrappers.

**Tech Stack:** httpx (async), FastAPI, pytest-asyncio.

---

## File Structure
- Create `brainpalace_dashboard/services/proxy.py` — `ProxyService`.
- Create `brainpalace_dashboard/services/capabilities.py` — OpenAPI introspection.
- Create `brainpalace_dashboard/api/routes_data.py` — data + action proxies.
- Modify `app.py` — include router; create/close shared httpx client in lifespan.

---

### Task 3.1: `ProxyService.request` — base_url lookup + error normalization

**Files:**
- Create: `brainpalace_dashboard/services/proxy.py`
- Test: `brainpalace-dashboard/tests/test_proxy.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_proxy.py
import httpx
import pytest
import brainpalace_dashboard.services.proxy as proxy_mod
from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr(
        proxy_mod, "instance_base_url",
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
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_proxy.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `proxy.py`**

```python
# brainpalace-dashboard/brainpalace_dashboard/services/proxy.py
"""ProxyService: normalized async calls to a project server's REST API."""

from __future__ import annotations

from typing import Any

import httpx

from brainpalace_dashboard.services.instances import InstanceService, InstanceNotFound

_instances = InstanceService()


def instance_base_url(id_: str) -> str:
    """Resolve an instance id to its live base_url ('' if not running)."""
    for row in _instances.list():
        if row["id"] == id_:
            return row.get("base_url", "")
    return ""


class UpstreamError(Exception):
    def __init__(self, detail: str, upstream_status: int):
        self.detail = detail
        self.upstream_status = upstream_status
        super().__init__(detail)


class ProxyService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self, id_: str, method: str, path: str,
        json: Any | None = None, params: dict | None = None,
    ) -> Any:
        base = instance_base_url(id_)
        if not base:
            raise UpstreamError("instance not running or unknown", 502)
        url = f"{base}{path}"
        try:
            resp = await self._get_client().request(method, url, json=json, params=params)
        except httpx.HTTPError as e:
            raise UpstreamError(f"upstream unreachable: {e}", 502)
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail", body) if isinstance(body, dict) else str(body)
            except Exception:
                detail = resp.text
            raise UpstreamError(str(detail), resp.status_code)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return {"raw": resp.text}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_proxy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/proxy.py brainpalace-dashboard/tests/test_proxy.py
git commit -m "feat(dashboard): ProxyService with normalized upstream errors

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3.2: Capabilities (OpenAPI introspection)

**Files:**
- Create: `brainpalace_dashboard/services/capabilities.py`
- Test: `brainpalace-dashboard/tests/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_capabilities.py
from brainpalace_dashboard.services.capabilities import parse_openapi


def test_parse_openapi_flattens_paths():
    doc = {
        "paths": {
            "/health/status": {"get": {"summary": "Indexing Status", "tags": ["health"]}},
            "/query/": {"post": {"summary": "Query Documents", "tags": ["query"]}},
        }
    }
    caps = parse_openapi(doc)
    assert {"method": "GET", "path": "/health/status", "summary": "Indexing Status", "tag": "health"} in caps
    assert any(c["method"] == "POST" and c["path"] == "/query/" for c in caps)
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_capabilities.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# brainpalace-dashboard/brainpalace_dashboard/services/capabilities.py
"""Parse a project server's /openapi.json into a flat capability list."""

from __future__ import annotations

from typing import Any


def parse_openapi(doc: dict[str, Any]) -> list[dict[str, str]]:
    caps: list[dict[str, str]] = []
    for path, methods in (doc.get("paths") or {}).items():
        for method, spec in methods.items():
            tags = spec.get("tags") or [""]
            caps.append({
                "method": method.upper(),
                "path": path,
                "summary": spec.get("summary", ""),
                "tag": tags[0],
            })
    return caps
```

- [ ] **Step 4: Run to verify pass** → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/capabilities.py brainpalace-dashboard/tests/test_capabilities.py
git commit -m "feat(dashboard): OpenAPI capability parsing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3.3: Data + action proxy routes

**Files:**
- Create: `brainpalace_dashboard/api/routes_data.py`
- Modify: `app.py` (include router + lifespan to close proxy client)
- Test: `brainpalace-dashboard/tests/test_routes_data.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_routes_data.py
from fastapi.testclient import TestClient
import brainpalace_dashboard.api.routes_data as rd
from brainpalace_dashboard.app import create_app


class FakeProxy:
    def __init__(self):
        self.calls = []
    async def request(self, id_, method, path, json=None, params=None):
        self.calls.append((method, path))
        if path == "/health/status":
            return {"total_chunks": 9}
        if path == "/folders/":
            return {"folders": []}
        if path == "/cache/":
            return {"hit_rate": 0.9}
        return {"ok": True}


def test_status_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/status")
    assert resp.json()["total_chunks"] == 9
    assert ("GET", "/health/status") in fp.calls


def test_clear_cache_proxy(monkeypatch):
    fp = FakeProxy()
    monkeypatch.setattr(rd, "proxy", fp)
    client = TestClient(create_app())
    resp = client.delete("/dashboard/api/instances/abc/cache")
    assert resp.status_code == 200
    assert ("DELETE", "/cache/") in fp.calls
```

- [ ] **Step 2: Run to verify fail** → Expected: FAIL.

- [ ] **Step 3: Implement routes (map every proxy target from the index)**

```python
# brainpalace-dashboard/brainpalace_dashboard/api/routes_data.py
"""Per-instance data reads + action proxies."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import JSONResponse

from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError

router = APIRouter(prefix="/dashboard/api/instances/{id_}", tags=["data"])
proxy = ProxyService()


async def _call(id_, method, path, json=None, params=None):
    try:
        return await proxy.request(id_, method, path, json=json, params=params)
    except UpstreamError as e:
        return JSONResponse(
            status_code=e.upstream_status,
            content={"error": "upstream", "detail": e.detail, "upstream_status": e.upstream_status},
        )


# ---- reads ----
@router.get("/status")
async def status(id_: str):
    return await _call(id_, "GET", "/health/status")

@router.get("/providers")
async def providers(id_: str):
    return await _call(id_, "GET", "/health/providers")

@router.get("/folders")
async def folders(id_: str):
    return await _call(id_, "GET", "/folders/")

@router.get("/jobs")
async def jobs(id_: str):
    return await _call(id_, "GET", "/jobs/")

@router.get("/jobs/{job_id}")
async def job(id_: str, job_id: str):
    return await _call(id_, "GET", f"/jobs/{job_id}")

@router.get("/cache")
async def cache(id_: str):
    return await _call(id_, "GET", "/cache/")

@router.get("/graph")
async def graph(id_: str):
    # graph stats live inside /health/status; expose a focused view client-side.
    return await _call(id_, "GET", "/health/status")

@router.get("/memories")
async def memories(id_: str):
    return await _call(id_, "GET", "/memories/")

@router.get("/capabilities")
async def capabilities(id_: str):
    from brainpalace_dashboard.services.capabilities import parse_openapi
    doc = await _call(id_, "GET", "/openapi.json")
    if isinstance(doc, JSONResponse):
        return doc
    return parse_openapi(doc)


# ---- actions ----
@router.post("/index")
async def add_folder(id_: str, body: dict = Body(...)):
    return await _call(id_, "POST", "/index/", json=body)

@router.delete("/folders")
async def remove_folder(id_: str, body: dict = Body(...)):
    return await _call(id_, "DELETE", "/folders/", json=body)

@router.delete("/index")
async def reset_index(id_: str):
    return await _call(id_, "DELETE", "/index/")

@router.delete("/cache")
async def clear_cache(id_: str):
    return await _call(id_, "DELETE", "/cache/")

@router.delete("/jobs/{job_id}")
async def cancel_job(id_: str, job_id: str):
    return await _call(id_, "DELETE", f"/jobs/{job_id}")

@router.post("/git/reindex")
async def git_reindex(id_: str):
    return await _call(id_, "POST", "/git/reindex")

@router.post("/sessions/reindex")
async def sessions_reindex(id_: str):
    return await _call(id_, "POST", "/sessions/reindex")

@router.post("/memories/{memory_id}/obsolete")
async def memory_obsolete(id_: str, memory_id: str):
    return await _call(id_, "POST", f"/memories/{memory_id}/obsolete")

@router.delete("/memories/{memory_id}")
async def memory_delete(id_: str, memory_id: str):
    return await _call(id_, "DELETE", f"/memories/{memory_id}")

@router.post("/memories/rebuild")
async def memory_rebuild(id_: str):
    return await _call(id_, "POST", "/memories/rebuild")
```

Wire `app.py`: include router + close proxy on shutdown:

```python
from contextlib import asynccontextmanager
from brainpalace_dashboard.api import routes_data

@asynccontextmanager
async def lifespan(app):
    yield
    await routes_data.proxy.aclose()

# in create_app: app = FastAPI(..., lifespan=lifespan); app.include_router(routes_data.router)
```

- [ ] **Step 4: Run to verify pass** → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/api/routes_data.py brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/tests/test_routes_data.py
git commit -m "feat(dashboard): per-instance data + action proxy routes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3.4: Integration — proxy against a real server

**Files:**
- Test: `brainpalace-dashboard/tests/test_integration_proxy.py`

- [ ] **Step 1: Write the test** (reuse the start/stop helper pattern from plan 01 Task 1.6; start a real server, then assert):

```python
# brainpalace-dashboard/tests/test_integration_proxy.py
import pytest, httpx
pytestmark = pytest.mark.integration

def test_proxy_status_against_real_server(tmp_path, monkeypatch):
    from brainpalace_dashboard.services.instances import InstanceService, instance_id
    import brainpalace_dashboard.services.instances as inst_mod
    from brainpalace_dashboard.services.proxy import ProxyService

    root = tmp_path; state = root / ".brainpalace"; state.mkdir()
    (state / "config.yaml").write_text(
        "server:\n  host: 127.0.0.1\n  port: 8650\n  auto_port: true\nstorage:\n  backend: chroma\n"
    )
    monkeypatch.setattr(inst_mod, "get_registry",
        lambda: {str(root): {"state_dir": str(state), "project_name": "itest"}})
    svc = InstanceService(); iid = instance_id(str(root))
    svc.start(iid)
    try:
        import asyncio
        proxy = ProxyService()
        out = asyncio.get_event_loop().run_until_complete(
            proxy.request(iid, "GET", "/health/status"))
        assert "total_chunks" in out
    finally:
        svc.stop(iid)
```

- [ ] **Step 2: Run** → `poetry run pytest tests/test_integration_proxy.py -m integration -v` → PASS.
- [ ] **Step 3: Commit**

```bash
git add brainpalace-dashboard/tests/test_integration_proxy.py
git commit -m "test(dashboard): integration proxy against real server

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan 03 self-check
- [ ] Every proxy target from the index has a route (reads + one action per surface).
- [ ] Upstream errors normalized to `{error, detail, upstream_status}`; never a blank 500.
- [ ] `task test:dashboard` + `task check` green.
