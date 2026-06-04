# Dashboard Plan 04 — Query history (server feature) + queries API + logs tail

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–03. **This plan modifies the project server** (`brainpalace-server`) and the config schema (`brainpalace-cli`), then adds control-plane routes.

**Goal:** Persist every query (with truncated results) in a per-project SQLite log with retention ≥2 days, expose `GET /query/history[...]` + `GET /health/logs` on the server, add a `query_log` config section (so it auto-appears in the dashboard), and proxy history/replay through the control plane.

**Architecture:** A `QueryLogService` on the server writes fire-and-forget after each successful query. SQLite at `<state_dir>/query_log.db`. New config section `query_log.{enabled,retention_days}` added to `config_schema` and `VALID_TOP_LEVEL_KEYS`. Control-plane `routes_queries.py` proxies list/detail and runs live replay through the existing `/query/` endpoint.

**Tech Stack:** SQLite (stdlib `sqlite3`), FastAPI, pytest. Reuses ProxyService.

---

## File Structure
- Create `brainpalace-server/brainpalace_server/services/query_log.py` — `QueryLogService`.
- Modify `brainpalace-server/brainpalace_server/api/routers/query.py` — write hook + history endpoints.
- Modify `brainpalace-server/brainpalace_server/api/routers/health.py` — `/health/logs` tail.
- Modify `brainpalace-cli/brainpalace_cli/config_schema.py` — `query_log` section + `VALID_TOP_LEVEL_KEYS`.
- Modify `brainpalace-dashboard/.../ui_schema.py` — add `query_log` section to render order.
- Create `brainpalace-dashboard/brainpalace_dashboard/api/routes_queries.py`.
- Docs: `docs/USER_GUIDE.md`/`docs/ARCHITECTURE.md` mention + `docs/CHANGELOG.md`.

---

### Task 4.1: `QueryLogService` — schema, insert, list, detail, purge

**Files:**
- Create: `brainpalace-server/brainpalace_server/services/query_log.py`
- Test: `brainpalace-server/tests/test_query_log.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-server/tests/test_query_log.py
import time
from pathlib import Path
from brainpalace_server.services.query_log import QueryLogService


def test_insert_and_list(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    svc.record(query="hello", mode="hybrid", top_k=5, latency_ms=12.3,
               results=[{"score": 0.9, "path": "a.py", "lines": "1-10", "snippet": "x"}],
               alpha=0.5, filters={})
    rows = svc.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["query"] == "hello"
    assert rows[0]["result_count"] == 1
    assert "results" not in rows[0]  # list view omits payload


def test_detail_includes_results(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    qid = svc.record(query="q", mode="bm25", top_k=3, latency_ms=1.0,
                     results=[{"score": 0.5, "path": "b.py", "lines": "2-3", "snippet": "y"}],
                     alpha=0.0, filters={})
    detail = svc.get(qid)
    assert detail["results"][0]["path"] == "b.py"


def test_filters_by_mode_and_contains(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    svc.record(query="alpha bravo", mode="hybrid", top_k=5, latency_ms=1, results=[], alpha=0.5, filters={})
    svc.record(query="charlie", mode="bm25", top_k=5, latency_ms=1, results=[], alpha=0.0, filters={})
    assert len(svc.list_recent(mode="bm25")) == 1
    assert len(svc.list_recent(contains="bravo")) == 1


def test_purge_removes_old(tmp_path):
    svc = QueryLogService(tmp_path / "query_log.db")
    old_ts = time.time() - 10 * 86400
    svc.record(query="old", mode="hybrid", top_k=5, latency_ms=1, results=[], alpha=0.5, filters={}, ts=old_ts)
    svc.record(query="new", mode="hybrid", top_k=5, latency_ms=1, results=[], alpha=0.5, filters={})
    svc.purge(retention_days=7)
    rows = svc.list_recent()
    assert len(rows) == 1 and rows[0]["query"] == "new"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-server && poetry run pytest tests/test_query_log.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `query_log.py`**

```python
# brainpalace-server/brainpalace_server/services/query_log.py
"""Per-project SQLite log of queries + truncated results."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    query TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    result_count INTEGER NOT NULL,
    alpha REAL,
    filters_json TEXT,
    results_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_ts ON queries(ts);
CREATE INDEX IF NOT EXISTS idx_queries_mode ON queries(mode);
"""


class QueryLogService:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, *, query: str, mode: str, top_k: int, latency_ms: float,
               results: list[dict[str, Any]], alpha: float | None = None,
               filters: dict | None = None, ts: float | None = None) -> str:
        qid = uuid.uuid4().hex
        slim = [
            {"score": r.get("score"), "path": r.get("path"),
             "lines": r.get("lines"), "snippet": (r.get("snippet") or "")[:500]}
            for r in results[:top_k]
        ]
        with self._conn() as c:
            c.execute(
                "INSERT INTO queries (id, ts, mode, query, top_k, latency_ms, "
                "result_count, alpha, filters_json, results_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (qid, ts or time.time(), mode, query, top_k, latency_ms,
                 len(results), alpha, json.dumps(filters or {}), json.dumps(slim)),
            )
        return qid

    def list_recent(self, *, since: float | None = None, mode: str | None = None,
                    contains: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        clauses, params = [], []
        if since is not None:
            clauses.append("ts >= ?"); params.append(since)
        if mode:
            clauses.append("mode = ?"); params.append(mode)
        if contains:
            clauses.append("query LIKE ?"); params.append(f"%{contains}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = ("SELECT id, ts, mode, query, top_k, latency_ms, result_count, alpha "
               f"FROM queries{where} ORDER BY ts DESC LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def get(self, qid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM queries WHERE id = ?", (qid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["results"] = json.loads(d.pop("results_json") or "[]")
        d["filters"] = json.loads(d.pop("filters_json") or "{}")
        return d

    def purge(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        with self._conn() as c:
            cur = c.execute("DELETE FROM queries WHERE ts < ?", (cutoff,))
            return cur.rowcount
```

- [ ] **Step 4: Run to verify pass** → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/query_log.py brainpalace-server/tests/test_query_log.py
git commit -m "feat(server): QueryLogService SQLite store for query history

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4.2: Wire the write hook into the query endpoint (fire-and-forget)

**Files:**
- Modify: `brainpalace-server/brainpalace_server/api/routers/query.py`
- Modify: server app startup (`api/main.py`) to attach `query_log_service` to `app.state`
- Test: `brainpalace-server/tests/test_query_logging_hook.py`

- [ ] **Step 1: Read how other services attach to `app.state`**

Run: `grep -nE "app.state\.|request.app.state\." brainpalace-server/brainpalace_server/api/main.py | head`
Mirror the existing pattern (e.g. how `query_service`/`indexing_service` are set during lifespan). Identify the server's state-dir env/config so the db path is `<state_dir>/query_log.db`.

- [ ] **Step 2: Write the failing test**

```python
# brainpalace-server/tests/test_query_logging_hook.py
def test_query_logs_after_success(monkeypatch):
    """A successful query writes one row to the query log."""
    from brainpalace_server.api.routers import query as qmod

    recorded = {}
    class FakeLog:
        enabled = True
        def record(self, **kw): recorded.update(kw); return "id1"
    # Drive the helper used by the endpoint directly:
    qmod._log_query(FakeLog(), query="hi", mode="hybrid", top_k=5,
                    latency_ms=3.0, results=[{"path": "a"}], alpha=0.5, filters={})
    assert recorded["query"] == "hi"
    assert recorded["mode"] == "hybrid"
```

- [ ] **Step 3: Implement the hook helper + call site**

In `query.py` add a small helper that never raises:

```python
def _log_query(log_service, **fields) -> None:
    """Best-effort write to the query log. Never raises."""
    try:
        if log_service is not None and getattr(log_service, "enabled", True):
            log_service.record(**fields)
    except Exception:  # logging must never break a query
        logger.debug("query log write failed", exc_info=True)
```

After `response = await query_service.execute_query(request_body)` and before `return response`, extract slim result fields from `response` (read `QueryResponse` shape — likely `response.results` with `score`, file path, line span, snippet; map to `path/lines/snippet`) and call:

```python
    log_service = getattr(request.app.state, "query_log_service", None)
    _log_query(
        log_service,
        query=query, mode=request_body.mode.value, top_k=request_body.top_k,
        latency_ms=getattr(response, "took_ms", 0.0),
        results=[
            {"score": getattr(r, "score", None),
             "path": getattr(r, "file_path", getattr(r, "path", None)),
             "lines": getattr(r, "line_range", None),
             "snippet": getattr(r, "snippet", getattr(r, "content", ""))}
            for r in getattr(response, "results", [])
        ],
        alpha=request_body.alpha,
        filters={"source_types": request_body.source_types, "languages": request_body.languages},
    )
```

> Read the real `QueryResponse`/result model field names (`grep -n "class QueryResponse" -A40 brainpalace-server/brainpalace_server/models/query.py`) and use the exact attributes; the `getattr` fallbacks above are a safety net, not an excuse to skip checking.

In `api/main.py` lifespan, construct `app.state.query_log_service = QueryLogService(state_dir / "query_log.db")` gated by config `query_log.enabled` (default True) and env `QUERY_LOG_ENABLED`. Set `.enabled` attribute and `.retention_days` from config; call `purge(retention_days)` on startup.

- [ ] **Step 4: Run** → `cd brainpalace-server && poetry run pytest tests/test_query_logging_hook.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/api/routers/query.py brainpalace-server/brainpalace_server/api/main.py brainpalace-server/tests/test_query_logging_hook.py
git commit -m "feat(server): log queries to query history (fire-and-forget)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4.3: History + logs endpoints on the server

**Files:**
- Modify: `brainpalace-server/brainpalace_server/api/routers/query.py` (GET /history, /history/{qid})
- Modify: `brainpalace-server/brainpalace_server/api/routers/health.py` (GET /logs)
- Test: `brainpalace-server/tests/test_query_history_endpoints.py`

- [ ] **Step 1: Write the failing test** (use the server `TestClient` with a stubbed `app.state.query_log_service`):

```python
# brainpalace-server/tests/test_query_history_endpoints.py
from fastapi.testclient import TestClient

def _client_with_log(rows, detail=None):
    from brainpalace_server.api.main import app
    class FakeLog:
        enabled = True
        def list_recent(self, **kw): return rows
        def get(self, qid): return detail
    app.state.query_log_service = FakeLog()
    return TestClient(app)

def test_history_list():
    c = _client_with_log([{"id": "1", "query": "x", "mode": "hybrid", "result_count": 2}])
    r = c.get("/query/history?limit=10")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "1"

def test_history_detail_404():
    c = _client_with_log([], detail=None)
    r = c.get("/query/history/missing")
    assert r.status_code == 404
```

- [ ] **Step 2: Implement endpoints**

In `query.py`:

```python
@router.get("/history", summary="Query History")
async def query_history(
    request: Request, since: float | None = None, mode: str | None = None,
    contains: str | None = None, limit: int = 100, offset: int = 0,
):
    log = getattr(request.app.state, "query_log_service", None)
    if log is None:
        return []
    return log.list_recent(since=since, mode=mode, contains=contains, limit=limit, offset=offset)


@router.get("/history/{qid}", summary="Query History Detail")
async def query_history_detail(request: Request, qid: str):
    log = getattr(request.app.state, "query_log_service", None)
    detail = log.get(qid) if log else None
    if detail is None:
        raise HTTPException(status_code=404, detail="query not found")
    return detail
```

In `health.py` add a bounded log tail (find the server's log file path; if logging writes to a file under state_dir, tail it; otherwise return the in-memory ring buffer if one exists — read how the server configures logging first):

```python
@router.get("/logs", summary="Recent server logs")
async def recent_logs(request: Request, lines: int = 200, level: str | None = None):
    path = getattr(request.app.state, "log_file_path", None)
    if not path:
        return {"lines": []}
    from collections import deque
    with open(path, "r", errors="replace") as f:
        tail = list(deque(f, maxlen=max(1, min(lines, 2000))))
    if level:
        tail = [ln for ln in tail if level.upper() in ln]
    return {"lines": tail}
```

> If the server has no file logging today, add a minimal `RotatingFileHandler` to `<state_dir>/server.log` in `main.py` and set `app.state.log_file_path`. Keep it small (1MB x 3).

- [ ] **Step 3: Run** → `cd brainpalace-server && poetry run pytest tests/test_query_history_endpoints.py -v` → PASS.

- [ ] **Step 4: Commit**

```bash
git add brainpalace-server/brainpalace_server/api/routers/query.py brainpalace-server/brainpalace_server/api/routers/health.py brainpalace-server/tests/test_query_history_endpoints.py
git commit -m "feat(server): query history + logs tail endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4.4: Add `query_log` config section to the schema

**Files:**
- Modify: `brainpalace-cli/brainpalace_cli/config_schema.py`
- Modify: `brainpalace-dashboard/.../ui_schema.py` (render order + bool/int types)
- Test: `brainpalace-cli/tests/test_config_query_log.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-cli/tests/test_config_query_log.py
from brainpalace_cli import config_schema as cs

def test_query_log_is_valid_top_level():
    assert "query_log" in cs.VALID_TOP_LEVEL_KEYS

def test_query_log_known_fields():
    assert {"enabled", "retention_days"} <= cs.QUERY_LOG_KNOWN_FIELDS

def test_query_log_validates():
    errs = cs.validate_config_dict({"query_log": {"enabled": True, "retention_days": 7}})
    assert not [e for e in errs if e.field.startswith("query_log")]
```

- [ ] **Step 2: Implement** — in `config_schema.py`: add `"query_log"` to `VALID_TOP_LEVEL_KEYS`; add `QUERY_LOG_KNOWN_FIELDS = {"enabled", "retention_days"}`; add a `_SECTION_SCHEMA["query_log"]` entry with `type_fields={"enabled": (bool, "query_log.enabled must be a boolean"), "retention_days": (int, "query_log.retention_days must be an integer")}`.

- [ ] **Step 3: Update `ui_schema.py`** — add `("query_log", "Query Log")` to `SECTION_ORDER`, `SECTION_KNOWN["query_log"] = cs.QUERY_LOG_KNOWN_FIELDS`, add `query_log.enabled` to `_BOOL_FIELDS` and `query_log.retention_days` to `_INT_FIELDS` with override `{"min": 0, "max": 365, "help": "0 = keep forever"}`.

- [ ] **Step 4: Run** both: `cd brainpalace-cli && poetry run pytest tests/test_config_query_log.py -v` and `cd ../brainpalace-dashboard && poetry run pytest tests/test_ui_schema.py -v` → PASS. (The UISchema coverage test now also covers `query_log` automatically.)

- [ ] **Step 5: Commit**

```bash
git add brainpalace-cli/brainpalace_cli/config_schema.py brainpalace-cli/tests/test_config_query_log.py brainpalace-dashboard/brainpalace_dashboard/ui_schema.py
git commit -m "feat(config): add query_log section; surface in dashboard schema

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4.5: Control-plane queries routes (history list/detail/replay)

**Files:**
- Create: `brainpalace-dashboard/brainpalace_dashboard/api/routes_queries.py`
- Modify: `app.py`
- Test: `brainpalace-dashboard/tests/test_routes_queries.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_routes_queries.py
from fastapi.testclient import TestClient
import brainpalace_dashboard.api.routes_queries as rq
from brainpalace_dashboard.app import create_app

class FakeProxy:
    async def request(self, id_, method, path, json=None, params=None):
        if path == "/query/history": return [{"id": "1", "query": "x"}]
        if path == "/query/history/1": return {"id": "1", "results": []}
        if path == "/query/": return {"results": [{"path": "a.py"}]}
        return {}

def test_history_list(monkeypatch):
    monkeypatch.setattr(rq, "proxy", FakeProxy())
    c = TestClient(create_app())
    assert c.get("/dashboard/api/instances/abc/queries").json()[0]["id"] == "1"

def test_replay(monkeypatch):
    monkeypatch.setattr(rq, "proxy", FakeProxy())
    c = TestClient(create_app())
    r = c.post("/dashboard/api/instances/abc/queries/replay",
               json={"query": "x", "mode": "hybrid", "top_k": 5})
    assert r.json()["results"][0]["path"] == "a.py"
```

- [ ] **Step 2: Implement**

```python
# brainpalace-dashboard/brainpalace_dashboard/api/routes_queries.py
from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError

router = APIRouter(prefix="/dashboard/api/instances/{id_}/queries", tags=["queries"])
proxy = ProxyService()

async def _call(id_, method, path, json=None, params=None):
    try:
        return await proxy.request(id_, method, path, json=json, params=params)
    except UpstreamError as e:
        return JSONResponse(status_code=e.upstream_status,
                            content={"error": "upstream", "detail": e.detail,
                                     "upstream_status": e.upstream_status})

@router.get("")
async def history(id_: str, since: float | None = None, mode: str | None = None,
                  contains: str | None = None, limit: int = 100, offset: int = 0):
    params = {k: v for k, v in dict(since=since, mode=mode, contains=contains,
                                    limit=limit, offset=offset).items() if v is not None}
    return await _call(id_, "GET", "/query/history", params=params)

@router.get("/{qid}")
async def detail(id_: str, qid: str):
    return await _call(id_, "GET", f"/query/history/{qid}")

@router.post("/replay")
async def replay(id_: str, body: dict = Body(...)):
    payload = {"query": body["query"], "mode": body.get("mode", "hybrid"),
               "top_k": body.get("top_k", 5)}
    if "alpha" in body: payload["alpha"] = body["alpha"]
    return await _call(id_, "POST", "/query/", json=payload)
```

Wire `app.py` include_router.

- [ ] **Step 3: Run** → PASS.
- [ ] **Step 4: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/api/routes_queries.py brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/tests/test_routes_queries.py
git commit -m "feat(dashboard): query history + replay routes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4.6: Docs + freshness

- [ ] Add a "Query history" subsection to `docs/USER_GUIDE.md` (or the right audited doc) describing `query_log.{enabled,retention_days}`, default 7-day retention, `QUERY_LOG_ENABLED=false` kill switch, and the new endpoints. Bump that doc's `last_validated` to today.
- [ ] Add a `docs/CHANGELOG.md` entry under Unreleased: "Server query history (SQLite) + dashboard Queries tab".
- [ ] Commit:

```bash
git add docs/
git commit -m "docs: query history feature + changelog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan 04 self-check
- [ ] Running a query writes one history row; history filters by mode/contains/since; detail returns results; retention purge works.
- [ ] `query_log` appears in `GET /dashboard/api/schema` automatically (no extra UI wiring).
- [ ] Server + cli + dashboard test suites green; `task check` green.
