# Dashboard Plan 06 — Remaining tabs: Folders, Queries, Jobs, Cache, Graph, Sessions, Logs

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 03–05. Invoke the **`frontend`** skill before building UI.

**Goal:** Implement the seven remaining per-instance tabs against the proxy + queries endpoints, each with click-only actions, confirm dialogs on destructive ops, live refresh, and Recharts stats.

**Architecture:** Each tab is a route under the selected-instance shell; data via TanStack Query against `/dashboard/api/instances/{id}/...`. Destructive actions go through the shared `ConfirmDialog`. Live data (jobs, logs) uses polling or the SSE stream (Task 6.8).

**Tech Stack:** React/TS, TanStack Query, Recharts, Vitest.

---

## File Structure
- Create `frontend/src/tabs/{Folders,Queries,Jobs,Cache,Graph,Sessions,Logs}.tsx`
- Extend `frontend/src/api/client.ts` with the data/action calls.
- Create `frontend/src/components/{QueryDrawer,JobProgress,HitRateGauge,FolderPicker}.tsx`
- Backend: add SSE `routes_events.py` (Task 6.8).

---

### Task 6.1: API client extensions

**Files:** Modify `frontend/src/api/client.ts`. Test: `frontend/src/api/client.data.test.ts`.

- [ ] **Step 1: Failing test** — stub fetch; assert `getFolders(id)`, `getJobs(id)`, `getCache(id)`, `getQueries(id, {mode})` build the right URLs and parse JSON.
- [ ] **Step 2: Implement** add:

```ts
export const getStatus = (id: string) => fetch(`/dashboard/api/instances/${id}/status`).then(r => r.json());
export const getFolders = (id: string) => fetch(`/dashboard/api/instances/${id}/folders`).then(r => r.json());
export const getJobs = (id: string) => fetch(`/dashboard/api/instances/${id}/jobs`).then(r => r.json());
export const getCache = (id: string) => fetch(`/dashboard/api/instances/${id}/cache`).then(r => r.json());
export const getProviders = (id: string) => fetch(`/dashboard/api/instances/${id}/providers`).then(r => r.json());
export const getMemories = (id: string) => fetch(`/dashboard/api/instances/${id}/memories`).then(r => r.json());
export const clearCache = (id: string) => fetch(`/dashboard/api/instances/${id}/cache`, { method: "DELETE" }).then(r => r.json());
export const resetIndex = (id: string) => fetch(`/dashboard/api/instances/${id}/index`, { method: "DELETE" }).then(r => r.json());
export const addFolder = (id: string, body: object) => fetch(`/dashboard/api/instances/${id}/index`, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify(body) }).then(r => r.json());
export const removeFolder = (id: string, path: string) => fetch(`/dashboard/api/instances/${id}/folders`, { method: "DELETE", headers: {"content-type":"application/json"}, body: JSON.stringify({ path }) }).then(r => r.json());
export const cancelJob = (id: string, jobId: string) => fetch(`/dashboard/api/instances/${id}/jobs/${jobId}`, { method: "DELETE" }).then(r => r.json());
export const gitReindex = (id: string) => fetch(`/dashboard/api/instances/${id}/git/reindex`, { method: "POST" }).then(r => r.json());
export const sessionsReindex = (id: string) => fetch(`/dashboard/api/instances/${id}/sessions/reindex`, { method: "POST" }).then(r => r.json());
export const memoryObsolete = (id: string, mid: string) => fetch(`/dashboard/api/instances/${id}/memories/${mid}/obsolete`, { method: "POST" }).then(r => r.json());
export const memoryDelete = (id: string, mid: string) => fetch(`/dashboard/api/instances/${id}/memories/${mid}`, { method: "DELETE" }).then(r => r.json());
export const memoryRebuild = (id: string) => fetch(`/dashboard/api/instances/${id}/memories/rebuild`, { method: "POST" }).then(r => r.json());

export function getQueries(id: string, q: { mode?: string; contains?: string; since?: number; limit?: number } = {}) {
  const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]));
  return fetch(`/dashboard/api/instances/${id}/queries?${p}`).then(r => r.json());
}
export const getQueryDetail = (id: string, qid: string) => fetch(`/dashboard/api/instances/${id}/queries/${qid}`).then(r => r.json());
export const replayQuery = (id: string, body: { query: string; mode: string; top_k: number }) =>
  fetch(`/dashboard/api/instances/${id}/queries/replay`, { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify(body) }).then(r => r.json());
export const getLogs = (id: string, lines = 200, level?: string) => {
  const p = new URLSearchParams({ lines: String(lines), ...(level ? { level } : {}) });
  return fetch(`/dashboard/api/instances/${id}/logs`, ).then(r => r.json()); // proxy added in Task 6.7
};
```

- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): data/action API client extensions`).

---

### Task 6.2: Folders / Index tab

**Files:** `frontend/src/tabs/Folders.tsx`, `components/FolderPicker.tsx`, `JobProgress.tsx`. Test: `Folders.test.tsx`.

- [ ] **Step 1: Failing test** — mock `getFolders` → two folders with path/file_count/chunk_count/watch; assert table renders; **Remove** opens ConfirmDialog then calls `removeFolder(id, path)`; **Add folder** opens FolderPicker, choosing a path + type-preset dropdown then **Add** calls `addFolder(id, {path, include_type})`; while a job runs, `JobProgress` shows percent (poll `getJobs`).
- [ ] **Step 2: Implement** — folder table (path, files, chunks, watch toggle, last indexed), Add-folder flow (path text input is unavoidable for a path, but type preset + watch mode are dropdowns; pull presets from `/types` proxy if added, else a static preset list mirroring `brainpalace types`), Remove/Re-index/Reset-index (danger, ConfirmDialog), live `JobProgress` from `getJobs` poll (`refetchInterval: 1500` while any job running).
- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Folders/Index tab`).

---

### Task 6.3: Queries tab (history + drawer + replay + charts)

**Files:** `frontend/src/tabs/Queries.tsx`, `components/QueryDrawer.tsx`. Test: `Queries.test.tsx`.

- [ ] **Step 1: Failing test** — mock `getQueries` → rows with ts/mode/top_k/latency_ms/result_count/query; assert table renders, default range covers ≥2 days; filter by mode dropdown re-queries with `{mode}`; clicking a row opens `QueryDrawer` (mock `getQueryDetail` → results with score/path/lines/snippet); **Re-run** calls `replayQuery(id, {query, mode, top_k})` and shows fresh results; a latency chart renders.
- [ ] **Step 2: Implement** — history table (relative time, mode badge, latency, #results, truncated query), filter bar (mode dropdown, date-range buttons "24h/2d/7d", contains search), `QueryDrawer` showing full query + ranked results (`file:line`, score bar, snippet), **Re-run** button, Recharts volume-over-time + latency line.
- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Queries history tab with replay`).

---

### Task 6.4: Jobs tab

**Files:** `frontend/src/tabs/Jobs.tsx`. Test: `Jobs.test.tsx`.

- [ ] **Step 1: Failing test** — mock `getJobs` → running + completed job; assert columns (id, type, status, progress, started/finished, error); **Cancel** on a running job opens ConfirmDialog then calls `cancelJob`; auto-refresh while running.
- [ ] **Step 2: Implement** — jobs table, status badges, progress bar, Cancel action, `refetchInterval: 2000` when any running.
- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Jobs tab`).

---

### Task 6.5: Cache + Graph tabs

**Files:** `frontend/src/tabs/Cache.tsx`, `Graph.tsx`, `components/HitRateGauge.tsx`. Tests: `Cache.test.tsx`, `Graph.test.tsx`.

- [ ] **Step 1: Failing tests** — Cache: mock `getCache` → entries/hit_rate/hits/misses; gauge renders; **Clear cache** confirm→`clearCache`. Graph: mock `getStatus` → graph entities/rels/enabled/store_type; cards render; **Re-index git history** confirm→`gitReindex`.
- [ ] **Step 2: Implement** both tabs with stat cards + `HitRateGauge` (Recharts radial) and the two guarded actions.
- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Cache + Graph tabs`).

---

### Task 6.6: Sessions / Memory tab

**Files:** `frontend/src/tabs/Sessions.tsx`. Test: `Sessions.test.tsx`.

- [ ] **Step 1: Failing test** — mock `getStatus` (session archive/index fields) + `getMemories` → list; assert archive on/off + counts render; a memory row's **Obsolete**→`memoryObsolete`, **Delete**→confirm→`memoryDelete`; **Rebuild shadow index**→`memoryRebuild`; **Re-index transcripts**→`sessionsReindex`.
- [ ] **Step 2: Implement** — session archive card (on/off, files, size), session index card (on/off, watching/idle, chunk + curated-memory counts), curated memories list with per-row actions + the two global actions. (Field names: read `/health/status` JSON for the exact session/memory keys; mirror what `brainpalace status` prints.)
- [ ] **Step 3: Run** → PASS. **Step 4: Commit** (`feat(dashboard-ui): Sessions/Memory tab`).

---

### Task 6.7: Logs proxy + Logs tab

**Files:** Modify `brainpalace_dashboard/api/routes_data.py` (add `/logs` proxy). Create `frontend/src/tabs/Logs.tsx`. Tests: backend `test_routes_data.py` (extend), `Logs.test.tsx`.

- [ ] **Step 1: Backend failing test** — add a case asserting `GET /dashboard/api/instances/{id}/logs?lines=50` proxies to server `/health/logs`. Implement the route:

```python
@router.get("/logs")
async def logs(id_: str, lines: int = 200, level: str | None = None):
    params = {"lines": lines, **({"level": level} if level else {})}
    return await _call(id_, "GET", "/health/logs", params=params)
```

- [ ] **Step 2: Frontend failing test** — mock `getLogs` → `{lines:[...]}`; assert lines render; level filter dropdown re-queries; auto-tail toggle.
- [ ] **Step 3: Implement** Logs tab: monospace log pane, level filter dropdown, lines selector (100/200/500/1000 buttons), auto-tail toggle (poll every 3s when on).
- [ ] **Step 4: Run** both → PASS. **Step 5: Commit** (`feat(dashboard): logs proxy + Logs tab`).

---

### Task 6.8: SSE live updates (optional-but-recommended; powers status freshness)

**Files:** Create `brainpalace_dashboard/api/routes_events.py`. Modify `app.py`. Frontend `src/state/useLiveInstances.ts`. Tests: backend `test_routes_events.py`, frontend `useLiveInstances.test.ts`.

- [ ] **Step 1: Backend failing test** — assert `GET /dashboard/api/events` returns `text/event-stream` and emits at least one `instances` event (use a short-circuit: a `max_ticks=1` query param for testability).
- [ ] **Step 2: Implement** with `sse-starlette` `EventSourceResponse`, emitting `{event:"instances", data: service.list()}` every `poll_s` (default 5). Add `max_ticks` param defaulting to None for tests.
- [ ] **Step 3: Frontend** `useLiveInstances` subscribes to `EventSource("/dashboard/api/events")`, feeds TanStack Query cache `setQueryData(["instances"], ...)`; falls back to polling if SSE errors.
- [ ] **Step 4: Run** both → PASS. **Step 5: Commit** (`feat(dashboard): SSE live instance updates`).

---

### Task 6.9: Rebuild static + tab smoke

- [ ] `cd frontend && npm run build`; commit `static/`.
- [ ] Manual smoke against a real running instance: every tab loads real data; one action per tab succeeds (clear cache, cancel job, re-run query, remove a test folder, obsolete a memory).
- [ ] Commit (`build(dashboard-ui): rebuild static after tabs`).

---

## Plan 06 self-check
- [ ] All 7 tabs render real data; every destructive action is confirm-gated; no free typing except a folder path and the contains-search box.
- [ ] Queries tab shows ≥2 days and replays; Jobs/Logs live-refresh.
- [ ] `task test:dashboard` + frontend `vitest run` green.
