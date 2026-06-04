# BrainPalace Control-Plane Dashboard — Design & Autonomous Implementation Plan

**Date:** 2026-06-04
**Status:** Approved for autonomous implementation (subagent-driven)
**Author:** Brainstorm session (no open questions — all decisions pre-made with best-choice defaults)

---

## 0. How to use this document

This spec is written so an AI model can implement the entire feature **autonomously, with no
further questions**. Every decision is already made. Each phase has: goal, files to
create/change, exact contracts, and binary acceptance criteria. Implement phases in order.
After each phase, run `task before-push` (or the phase-local test target) and do not advance
until green.

Hard rules inherited from the repo (`CLAUDE.md`):
- **Setup-surface parity**: CLI · plugin · MCP must stay in sync. The dashboard adds a **fourth
  surface** and a new parity gate (Phase 8).
- **Doc freshness**: any audited doc you touch must get its `last_validated` bumped.
- **Never push `stable`**; `task before-push` must pass before any merge.
- Dogfood `brainpalace query` for codebase search.

---

## 1. Problem statement

BrainPalace runs **one server per project** (auto-discovered via `.brainpalace/runtime.json`
and a global `registry.json`). Today the only way to manage instances, edit config, inspect
indexed data, or see query activity is the CLI. We want a **professional, informative web
dashboard** — a single control plane — that can:

1. List **all** instances (running + known-but-stopped), with live health.
2. **Start / stop / restart** each instance (per project / per folder root).
3. Edit **every** config option through **click-only** controls (no free typing unless a value
   is inherently free-text, e.g. a model name or API-key env var name).
4. **Batch** config edits and commit them on one button: **Save** or **Save + Restart**.
5. Show **real statistics** per instance (documents, chunks, folders, cache, jobs, graph,
   providers, watcher).
6. Show **query history with results for at least the last 2 days** (new capability — see §6).
7. Present all of this in a **tabbed** UI, not one long page.
8. **Auto-include every future feature**: when a new config option, CLI command, server
   endpoint, or displayable datum is added, it must surface in the dashboard — enforced by a
   **release-time parity gate** (Phase 8) so drift fails CI before release.

---

## 2. Architecture decision (chosen)

### 2.1 Control plane = standalone aggregator daemon

A **new, separate process** — the *Dashboard control plane* — that:
- Reads the global `registry.json` (XDG state) + each project's `.brainpalace/runtime.json`.
- Proxies to each per-project server's existing REST API for live data.
- Reuses the CLI's existing lifecycle logic (`start.py` / `stop.py`) to start/stop/restart
  instances and to read/write each project's `config.yaml`.
- Serves the SPA + a thin `/dashboard/api/**` backend-for-frontend (BFF).

**Why standalone (not embedded in each project server):** the dashboard must outlive and
aggregate across instances; a per-project server cannot see siblings. Per-project servers stay
single-responsibility and unchanged (except the additive query-log feature in §6, which is
useful on its own). One process, one place to manage everything.

**Rejected alternative — embed a dashboard in every server:** N copies, no cross-instance view,
duplicated assets. Rejected.

### 2.2 Port scheme (chosen — improves on the "8000/8001…" idea)

The user proposed "main dashboard on 8000, other servers 8001…". **We do not renumber project
servers.** Project servers already self-allocate ports (`server.auto_port`, default on, scanning
from `server.port`/8000 upward) and record them in `registry.json`. Forcing a fixed 8001+ range
would collide with that allocator and break discovery.

**Decision:**
- **Dashboard control plane** binds a **dedicated, configurable port, default `8787`**
  (`dashboard.port`), on `127.0.0.1`. Chosen to sit clearly outside the project-server range so
  it never competes for 8000.
- **Project servers keep their existing dynamic ports.** The dashboard learns every server's URL
  from `registry.json` — zero renumbering, zero coupling.
- If `8787` is taken, the dashboard applies the same `find_available_port` scan (8787→8887) the
  servers use, and prints the resolved URL.

### 2.3 Component diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (SPA: React + TS + Tailwind + TanStack Query + Recharts) │
└───────────────▲───────────────────────────────┬──────────────────┘
                │  /dashboard/api/**  (JSON/SSE) │  static assets
┌───────────────┴───────────────────────────────▼──────────────────┐
│  Dashboard control-plane (FastAPI, port 8787)                     │
│  ┌──────────────┐ ┌───────────────┐ ┌──────────────────────────┐ │
│  │ InstanceSvc  │ │ ConfigSvc     │ │ ProxySvc (per-server REST)│ │
│  │ start/stop/  │ │ read/write    │ │ GET status/folders/jobs/  │ │
│  │ restart,     │ │ config.yaml,  │ │ cache/query-history/...   │ │
│  │ registry,    │ │ schema→UISchema│ │ via httpx                 │ │
│  │ health poll  │ │ validate      │ │                           │ │
│  └──────┬───────┘ └──────┬────────┘ └─────────┬────────────────┘ │
└─────────┼────────────────┼────────────────────┼──────────────────┘
          │ reuse CLI       │ reuse config_schema │ httpx
          ▼                 ▼                     ▼
   registry.json /     .brainpalace/        per-project servers
   runtime.json        config.yaml          (FastAPI, dynamic ports)
```

### 2.4 Where the code lives

New Poetry subpackage **`brainpalace-dashboard/`** (sibling of server/cli/plugin), so it builds
and tests independently and can be bundled by the CLI like the server already is.

```
brainpalace-dashboard/
  pyproject.toml                  # Poetry; deps: fastapi, uvicorn, httpx, brainpalace-cli (lifecycle/schema reuse)
  brainpalace_dashboard/
    __init__.py                   # __version__ (kept in lockstep — version_consistency test)
    app.py                        # FastAPI app factory, mounts SPA + /dashboard/api
    server.py                     # uvicorn launcher + port scan + pidfile/runtime for the dashboard itself
    config.py                     # dashboard config (port/host/poll interval/retention) from XDG config
    services/
      instances.py                # InstanceService: scan/start/stop/restart (wraps cli.commands.start/stop)
      config_svc.py               # ConfigService: read/write config.yaml + build UISchema from config_schema
      proxy.py                    # ProxyService: typed httpx calls to a project server's REST API
      capabilities.py             # introspect each server's /openapi.json → capability manifest
    api/
      __init__.py
      routes_instances.py         # /dashboard/api/instances[...]
      routes_config.py            # /dashboard/api/instances/{id}/config , /schema
      routes_data.py              # /dashboard/api/instances/{id}/{status,folders,jobs,cache,graph,providers,sessions}
      routes_queries.py           # /dashboard/api/instances/{id}/queries (history) + replay
      routes_events.py            # /dashboard/api/events (SSE: health/stat ticks)
    ui_schema.py                  # UI override layer (widget hints, labels, secret flags, model presets)
    static/                       # built SPA (vite build output) — committed or built in CI
  frontend/                       # SPA source (Vite). Built into ../brainpalace_dashboard/static
    package.json, vite.config.ts, tsconfig.json, tailwind.config.ts
    src/
      main.tsx, app.tsx, router.tsx, api/client.ts, api/types.ts
      components/  (Sidebar, InstancePicker, StatCard, DataTable, Charts, Toast, ConfirmDialog,
                   SchemaForm/*  ← renders controls from UISchema)
      tabs/  Overview.tsx Instances.tsx Config.tsx Folders.tsx Queries.tsx Jobs.tsx
             Cache.tsx Graph.tsx Sessions.tsx Logs.tsx
```

CLI integration: new command **`brainpalace dashboard`** (Phase 7) — `start` (default) / `stop`
/ `status`, launches/stops the control-plane process; `--port`, `--no-open` (don't open browser),
`--foreground`.

---

## 3. Tabbed UI — information architecture

Left sidebar = **instance picker** (all projects from registry, colored health dot) + global
actions. Top-level tabs operate on the **selected instance**, except **Instances** and
**Overview** which are cross-instance.

| Tab | Cross/Per | Content | Data source |
|-----|-----------|---------|-------------|
| **Overview** | Cross | Fleet summary cards: # running/stopped/unhealthy, total docs/chunks across fleet, aggregate cache hit-rate, recent query volume sparkline, alerts (provider misconfig, stale, unhealthy). | InstanceSvc + proxied `status` |
| **Instances** | Cross | Table of every project: name, path, status, port/URL, pid, uptime, version. Row actions (click-only): **Start, Stop, Restart, Open, Reveal path**. Bulk select → bulk start/stop. | InstanceSvc |
| **Config** | Per | **Schema-driven** form, grouped by section (Embedding, Summarization, Reranker, Storage, GraphRAG, API, Server, Project, Dashboard). All controls click-selectable (§5). Dirty-tracking banner with **Save** / **Save + Restart** / **Discard**. Inline validation from `config_schema.validate`. | ConfigSvc |
| **Folders / Index** | Per | Indexed folders table (path, file count, chunk count, watch mode, last indexed). Actions: **Add folder** (native-style path picker + type-preset dropdown), **Remove** (confirm), **Re-index**, **Toggle watch auto/off**, **Reset index** (danger, confirm). Live job progress when indexing. | proxy `folders`,`index`,`jobs` |
| **Queries** | Per | Query history (≥2 days, §6): time, mode, top-k, latency, #results, truncated text. Click a row → drawer with full query + ranked results (score, file:line, snippet). Filters: mode, date range, text contains. **Re-run** button replays the query live. Volume + latency charts. | proxy `query/history`, `query` |
| **Jobs** | Per | Async indexing job queue: id, type, status, progress, started/finished, error. Actions: **Cancel**, **View details**. Auto-refresh. | proxy `jobs` |
| **Cache** | Per | Embedding-cache metrics (entries, hit rate, hits/misses) + **Clear cache** (confirm). Hit-rate gauge. | proxy `cache` |
| **Graph** | Per | GraphRAG status: enabled, entities, relations, store type, extractor. **Re-index git history** action. | proxy `health/status`, `git/reindex` |
| **Sessions / Memory** | Per | Session archive (on/off, files, size) + session index (on/off, watching/idle, chunk + curated-memory counts). Curated memories list with **Obsolete**/**Delete**; **Rebuild shadow index**; **Re-index transcripts**. | proxy `sessions`,`memories`,`health/status` |
| **Logs** | Per | Tail of the project server's recent log lines (and the dashboard's own) via SSE; severity filter. | proxy (new lightweight `/health/logs` tail, see Phase 6 note) + control-plane log |

UX laws (apply everywhere):
- **No raw typing for choices.** Enums → segmented buttons or dropdown. Bools → toggle. Bounded
  ints → number stepper with min/max from schema. Provider/model → dropdown of known presets +
  an explicit "Custom…" affordance that *then* reveals a text field (typing only when truly
  custom). Free-text-by-nature fields (API-key **env var name**, base_url, custom model id) are
  text inputs but pre-filled and validated.
- **Secrets never shown.** `api_key` raw values are write-only/masked; UI steers users to
  `api_key_env` (env-var name) — matches existing config convention.
- **Batched save.** Edits mutate local form state only; nothing persists until **Save** /
  **Save + Restart**. A sticky banner shows "N unsaved changes".
- **Professional look:** dense but breathable dark/light theme, system font stack, 8px grid,
  Recharts for stats, skeleton loaders, optimistic toasts, confirm dialogs for destructive ops.

---

## 4. Control-plane API (BFF) — contracts

Base: `http://127.0.0.1:8787/dashboard/api`. All JSON. `{id}` = stable instance id =
URL-safe hash/slug of `project_root` (deterministic; computed by InstanceSvc).

Instances & lifecycle:
- `GET  /instances` → `[{id, name, project_root, state_dir, status, base_url, port, pid, started_at, uptime_s, version}]`
  (`status ∈ running|unhealthy|stopped|stale`). Merges registry + live health.
- `GET  /instances/{id}` → single, enriched with a one-shot `status` snapshot.
- `POST /instances/{id}/start` → spawns server (reuse `start.py` logic). Returns new instance row.
- `POST /instances/{id}/stop` → SIGTERM (reuse `stop.py`), `?force=true` → SIGKILL fallback.
- `POST /instances/{id}/restart` → stop→wait-for-exit→start. Used by **Save + Restart**.
- `POST /instances/register` `{path}` → register a project dir not yet in registry (init-only,
  optional convenience; does not run `init`).

Config:
- `GET  /schema` → **UISchema** (see §5): full field list with widget type, label, options,
  bounds, secret flag, section grouping, defaults. Derived from `config_schema` + `ui_schema.py`
  overrides. This single endpoint powers the entire Config form → new schema fields auto-appear.
- `GET  /instances/{id}/config` → current parsed `config.yaml` values (secrets masked).
- `PATCH /instances/{id}/config` `{values, restart: bool}` → validate (via
  `config_schema.validate`), write `config.yaml` atomically, optionally restart. Returns
  `{ok, errors:[{field,message,suggestion}], restarted}`. Rejects the whole batch on any error
  (all-or-nothing).

Per-instance data (thin proxies, normalized):
- `GET /instances/{id}/status` (health+indexing), `/folders`, `/jobs`, `/jobs/{job_id}`,
  `/cache`, `/providers`, `/graph`, `/sessions`, `/memories`.
- Action proxies: `POST /instances/{id}/index` (add folder), `DELETE …/folders` (remove),
  `POST …/reindex`, `DELETE …/cache`, `DELETE …/index` (reset), `POST …/git/reindex`,
  `POST …/sessions/reindex`, `POST …/memories/{mid}/obsolete`, `DELETE …/memories/{mid}`,
  `POST …/memories/rebuild`, `DELETE …/jobs/{job_id}` (cancel).

Queries (history is new — §6):
- `GET /instances/{id}/queries?since=…&mode=…&contains=…&limit=…` → history rows.
- `GET /instances/{id}/queries/{qid}` → full stored query + results payload.
- `POST /instances/{id}/queries/replay` `{qid}` or `{query,mode,top_k}` → live re-run via proxy.

Events:
- `GET /events` (SSE) → periodic `instances` health/stat ticks (interval = `dashboard.poll_s`,
  default 5s) so the UI live-updates without manual refresh.

Capabilities (powers auto-inclusion + Logs/explorer):
- `GET /instances/{id}/capabilities` → parsed `/openapi.json` of that server: list of
  `{method, path, summary, tag}`. Lets the UI detect endpoints a tab doesn't yet render and the
  parity test (Phase 8) assert coverage.

---

## 5. Schema-driven config (the auto-inclusion linchpin)

`config_schema.py` already encodes the **single source of truth**: `VALID_TOP_LEVEL_KEYS`,
per-section `*_KNOWN_FIELDS`, enum value sets (`VALID_*_PROVIDERS`, backends, store types,
extractors), and `*_TYPE_FIELDS` (int/bool). The Config form is **generated** from it.

**UISchema build (`config_svc.build_ui_schema()`):**
1. Start from `config_schema`: for each section, each known field →
   - if field appears in an enum set → `widget: "enum"`, `options: sorted(values)`.
   - else if in `*_TYPE_FIELDS` as `int` → `widget: "int"` (+ `min/max/step` from override or
     sane default); as `bool` → `widget: "toggle"`.
   - else → `widget: "text"` (default).
2. Apply **`ui_schema.py` override layer** (thin, declarative) for polish only:
   - human label + help text, section order, `secret: true` (api_key → masked/omit),
   - `presets` for otherwise-free text (e.g. embedding `model` presets per provider; reranker
     models), with "Custom…" escape hatch,
   - int bounds (ports 1–65535, pool sizes, hnsw params),
   - conditional visibility (e.g. `storage.postgres.*` only when `storage.backend == postgres`;
     `dashboard.*` section).
3. **Coverage is total by construction:** any field in `config_schema` with **no** override still
   renders with a sensible default widget. So a newly added schema field appears automatically.
   The override file only *improves* presentation; it is never *required* for a field to show.

**Parity guarantee:** Phase 8 adds a test asserting every `config_schema` field is reachable in
the generated UISchema (catches a schema field the builder skips), and every `ui_schema.py`
override key maps to a real `config_schema` field (catches stale overrides). New option → either
it auto-renders (pass) or, if intentionally hidden, must be added to an explicit
`DASHBOARD_HIDDEN_FIELDS` allowlist with a reason → forces a conscious decision before release.

---

## 6. New server capability — Query history (last ≥2 days)

No query logging exists today. Add an **additive, opt-outable** feature to the **project server**
(useful beyond the dashboard, keeps single-responsibility):

- **Storage:** SQLite at `.brainpalace/query_log.db` (table `queries`: `id, ts, mode, query,
  top_k, latency_ms, result_count, results_json, alpha, filters_json`). SQLite chosen over JSONL
  for indexed time/mode filtering and bounded growth.
- **Write path:** in `query.py` after a successful `execute_query`, fire-and-forget insert
  (never block or fail the query on log error). Truncate `results_json` to top-K minimal fields
  (score, file path, line range, snippet) to bound size.
- **Retention:** `query_log.retention_days` (default **7**, ≥2 satisfies requirement;
  `<=0` = forever). A lightweight purge on server start + daily.
- **Kill switch:** `query_log.enabled` (default true) + env `QUERY_LOG_ENABLED=false`. Add
  `query_log` to `VALID_TOP_LEVEL_KEYS` + schema (so it appears in the Config tab automatically).
- **New endpoints** (project server, `query` router):
  - `GET /query/history?since&mode&contains&limit&offset` → rows (no `results_json`).
  - `GET /query/history/{qid}` → one row incl. `results_json`.
- **Logs tail (Phase 6 minor):** add `GET /health/logs?lines=N&level=` returning the last N log
  lines from the server's log file, for the Logs tab. Bounded, read-only.

Because these are new server endpoints/config, they flow through the **same parity gate** — the
dashboard must render them, which it does (Queries + Logs tabs, schema-driven config).

---

## 7. Tech stack (chosen)

- **Backend (control plane):** FastAPI + uvicorn + httpx (async). Reuses `brainpalace-cli`
  (`commands.start/stop`, `config_schema`, `xdg_paths`, `discovery`) as a dependency — no logic
  duplication. SSE via `sse-starlette` or a plain `StreamingResponse`.
- **Frontend:** **Vite + React 18 + TypeScript + Tailwind CSS**, **TanStack Query** (server-state,
  caching, polling), **TanStack Router** (typed tabs), **Recharts** (stats), **Zod** (validate API
  payloads), **lucide-react** (icons). Rationale: a real component framework yields the
  "professional, informative" bar; schema-driven `SchemaForm` is far cleaner in React than in
  templated HTML; TanStack Query gives live updates with little code.
- **Build:** `vite build` → `brainpalace_dashboard/static/`. Committed build output **and** a
  CI/Taskfile target to rebuild. Served by FastAPI `StaticFiles` (SPA fallback to `index.html`).
- **No external services.** Localhost-only, no auth in v1 (binds `127.0.0.1`); a `--token` shared
  secret header is a documented optional hardening (Phase 7, off by default).

---

## 8. Cross-cutting concerns

- **Security:** bind `127.0.0.1` only. Destructive proxy actions (reset index, clear cache,
  delete memory, stop/restart) require a confirm dialog client-side; server-side they're plain
  proxies to existing guarded endpoints. Secrets masked in all config reads. Optional bearer
  token (`dashboard.token`) gates `/dashboard/api/**` when set.
- **Atomic config writes:** write to `config.yaml.tmp` then `os.replace`. Keep a `.bak` of the
  previous file so a bad Save is recoverable.
- **Restart safety:** restart = stop → `wait_for_process_exit` → start; on start failure, surface
  the preflight error (reuse `init --start` provider preflight rules) and **do not** leave the
  instance down silently — report status back to UI.
- **Works with zero servers running:** the dashboard is its own process and keeps a durable
  `dashboard_known.json` (XDG state) of every project it has seen. `registry.json` only tracks
  *running* servers and is pruned on stop, so the dashboard never relies on it for the full list.
  Instances/Overview/Config tabs are server-independent (Config edits `config.yaml` on disk and
  applies on next start); per-instance **data** tabs proxy a live server and render a clean
  "stopped — Start" state when it's down.
- **Stale / stopped handling:** a known project with a dead/absent process shows `stopped` and is
  still **Start**-able from its row; **Remove from list** (`DELETE /instances/{id}`) forgets it
  without touching anything on disk; **Register project** adds an existing project dir.
- **Errors:** every proxy normalizes upstream errors to `{error, detail, upstream_status}`; UI
  shows a toast, never a blank panel.
- **Performance:** health/stat polling batched and de-duped server-side (one fan-out per tick,
  cached for `poll_s`); SPA subscribes to one SSE stream.
- **Versioning:** `brainpalace_dashboard.__version__` kept in lockstep with server/cli (extend
  `test_version_consistency`).

---

## 9. Testing strategy

- **Backend unit:** UISchema build (every schema field covered; overrides valid), config
  read/write/validate round-trip + atomicity + masking, InstanceSvc id determinism, proxy error
  normalization, query-history store insert/query/retention purge.
- **Backend integration:** spin a real project server on an ephemeral port, register it, hit
  `/dashboard/api/instances/**` end-to-end (status, folders, start/stop/restart, query replay,
  history).
- **Frontend:** Vitest + Testing Library for `SchemaForm` (renders each widget type from a fixture
  UISchema, batches edits, emits one save payload), tab smoke tests with mocked API.
- **E2E (Playwright, in `e2e/`):** launch control plane against a temp project, click through:
  start instance → edit a config enum → Save+Restart → see new value → add folder → watch job →
  run/replay a query → see it in Queries history → stop instance.
- **Parity gate (Phase 8):** see §10.

---

## 10. The release-time auto-inclusion gate (Phase 8) — operationalizing the meta-requirement

New file `brainpalace-dashboard/tests/test_dashboard_parity.py` + Taskfile target
`lint:dashboard-parity`, wired into **`task before-push`** (so it blocks every push/release).

It asserts, failing loudly with the offending name and the fix:

1. **Config parity:** every `config_schema` section+field is present in the generated UISchema,
   OR explicitly listed in `DASHBOARD_HIDDEN_FIELDS` (with a reason string). Every `ui_schema.py`
   override key maps to a real schema field.
2. **Endpoint parity:** every project-server router prefix (enumerate from
   `api/routers/__init__.py` / app routes, or a checked-in `ENDPOINT_SURFACES` manifest) maps to a
   dashboard tab or an explicit `DASHBOARD_UNSURFACED_ENDPOINTS` allowlist (with reason).
3. **CLI parity:** every command added in `cli.py` (`cli.add_command(...)`) is classified in a
   checked-in `CLI_DASHBOARD_COVERAGE` map as `surfaced` (which tab/action) or `cli_only`
   (with reason). A new, unclassified command fails the test.

Plus a **`docs/CHANGELOG.md` reminder** and a new **`CLAUDE.md` "Dashboard parity" rule** (mirrors
the existing "Setup-surface parity" rule): *"When you add a config option, CLI command, server
endpoint, or user-facing datum, surface it in the dashboard (or allowlist it with a reason) in the
same change, and note it in the CHANGELOG."* Add it to `docs/RELEASING.md` pre-release checklist.

This converts "must auto-include every future feature" into an enforced, mechanical gate: drift
**cannot** reach a release because `before-push` fails first.

---

## 11. Phased implementation plan

Each phase is independently shippable and ends green. Subagent-driven: one subagent per phase (or
per bolded workstream), TDD where the skill applies.

### Phase 0 — Scaffold the subpackage
- Create `brainpalace-dashboard/` Poetry package: `pyproject.toml` (deps: fastapi, uvicorn,
  httpx, sse-starlette, `brainpalace-cli` path dep), `__init__.py` with `__version__` matching
  others, empty `app.py` returning a health route, packaging wired so `task install` builds it.
- Taskfile: add `install`/`test`/`check` hooks for the dashboard package; extend
  `test_version_consistency`.
- **Done when:** `task install` installs it; `GET /dashboard/api/health` returns 200 in a unit
  test; `task check` green.

### Phase 1 — InstanceService + lifecycle API
- `services/instances.py`: deterministic `id`, `list()` (merge registry + `scan_instances`
  health), `start/stop/restart` by reusing `cli.commands.start`/`stop` internals (extract shared
  helpers if needed — do **not** copy-paste lifecycle logic; refactor cli to expose callables).
- `api/routes_instances.py`: the §4 instance endpoints.
- **Done when:** integration test starts/stops/restarts a real ephemeral project server through
  the API; list shows correct status transitions.

### Phase 2 — ConfigService + schema-driven UISchema + config API
- `services/config_svc.py`: parse `config.yaml`, mask secrets, atomic write+`.bak`, validate via
  `config_schema.validate`, `build_ui_schema()` (§5). `ui_schema.py` override layer.
- `api/routes_config.py`: `GET /schema`, `GET/PATCH /instances/{id}/config` (all-or-nothing,
  optional restart).
- **Done when:** unit tests prove every schema field appears in UISchema; PATCH validates,
  writes atomically, masks secrets, and `restart:true` actually restarts.

### Phase 3 — ProxyService + per-instance data endpoints
- `services/proxy.py`: async httpx client per `base_url`, normalized errors, short cache.
- `services/capabilities.py`: fetch+parse `/openapi.json`.
- `api/routes_data.py`: status/folders/jobs/cache/providers/graph/sessions/memories + action
  proxies (§4).
- **Done when:** integration tests cover read + one action per surface against a live server.

### Phase 4 — Query history (server) + queries API (control plane)
- **Server (additive):** SQLite query log, write hook in `query.py`, retention purge, config
  (`query_log.*` in schema + `VALID_TOP_LEVEL_KEYS`), `GET /query/history[...]` endpoints,
  `GET /health/logs` tail. Update `docs/` + CHANGELOG; bump touched docs' `last_validated`.
- **Control plane:** `api/routes_queries.py` (history list/detail/replay).
- **Done when:** running a query creates a history row; history endpoints filter by mode/date/
  contains; replay returns live results; retention purge tested; server tests green.

### Phase 5 — SPA foundation + Instances/Overview/Config tabs
- Vite/React/TS/Tailwind scaffold in `frontend/`; `api/client.ts` (+Zod types), router, layout
  (sidebar instance picker, tab shell), theme, shared components (StatCard, DataTable, Toast,
  ConfirmDialog, Charts).
- `SchemaForm/*`: render controls **purely** from UISchema (enum→segmented/dropdown,
  bool→toggle, int→stepper, text/preset+Custom). Dirty-tracking, batched **Save** /
  **Save + Restart** / **Discard** banner, inline validation errors from PATCH.
- Implement **Overview**, **Instances** (row + bulk start/stop/restart), **Config** tabs.
- `vite build` → `static/`; FastAPI serves SPA with index fallback.
- **Done when:** Vitest covers SchemaForm widget rendering + single-batch save payload; manual/
  E2E: select instance, change an enum, Save+Restart, value persists.

### Phase 6 — Remaining tabs: Folders, Queries, Jobs, Cache, Graph, Sessions, Logs
- Build each tab against Phase 3/4 endpoints, with the click-only action set from §3, confirm
  dialogs for destructive ops, live job/log via SSE/poll, Recharts stats, query drawer + replay.
- **Done when:** each tab renders real data + its actions succeed against a live server; Logs tab
  tails via SSE.

### Phase 7 — CLI integration + dashboard self-lifecycle + docs
- `brainpalace dashboard [start|stop|status]` command (port scan, pidfile/runtime for the
  dashboard, `--foreground`, `--no-open`, opens browser to resolved URL). Optional
  `dashboard.token` hardening.
- Bundle the dashboard from the CLI like the server is bundled at runtime.
- Docs: `docs/DASHBOARD.md` (full guide, `last_validated`), README feature bullet, MCP/plugin
  notes if relevant, CHANGELOG.
- **Done when:** `brainpalace dashboard` launches the control plane and opens the UI; `stop`
  cleans up; CLI tests cover the command.

### Phase 8 — Auto-inclusion parity gate + governance
- `test_dashboard_parity.py` (config/endpoint/CLI parity, §10) + `lint:dashboard-parity` Taskfile
  target wired into `before-push`. Checked-in manifests/allowlists with reasons.
- Add **"Dashboard parity"** rule to `CLAUDE.md` and the pre-release step to `docs/RELEASING.md`.
- **Done when:** removing a tab/override or adding an unclassified config field/CLI command/
  endpoint makes `task before-push` fail with a clear message; full suite green.

### Phase 9 — E2E + polish + release
- Playwright E2E (§9 flow). Accessibility pass (keyboard nav, focus, contrast). Empty/loading/
  error states. Performance check (poll batching). Final `task before-push`.
- **Done when:** E2E green headless; `task before-push` green; CHANGELOG + version bumped per
  `docs/RELEASING.md`.

---

## 12. Out of scope (v1, YAGNI)
- Multi-user auth / RBAC / remote (non-localhost) access (only optional shared token).
- Editing config of a **stopped** instance's *running* behavior (you can still edit `config.yaml`
  for stopped instances; it applies on next start).
- Creating brand-new projects (`init`) from the UI — register/list/manage existing ones only.
- Historical metrics beyond query log (no time-series DB); stats are point-in-time + query log.

---

## 13. Acceptance (whole feature)
1. `brainpalace dashboard` opens a professional tabbed UI listing **all** instances.
2. Start/stop/restart any instance from the UI; per-project ("per folder") lifecycle works.
3. Every config option is editable via **click-only** controls; **Save** and **Save + Restart**
   both work; edits are batched (one write).
4. Real per-instance statistics render (docs/chunks/folders/cache/jobs/graph/providers/watcher).
5. Query history with results for **≥2 days** is visible, filterable, and replayable.
6. Adding a new config field / CLI command / server endpoint **fails `task before-push`** until it
   is surfaced in the dashboard (or explicitly allowlisted) — proving auto-inclusion is enforced.
7. `task before-push` green; docs updated with bumped `last_validated`.
