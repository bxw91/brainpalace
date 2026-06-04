# Control-Plane Dashboard — Plan Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build a standalone web control plane that manages every BrainPalace project server — list/start/stop/restart instances, edit all config via click-only batched forms, show real stats, show query history (≥2 days), in a tabbed React SPA — with a release-time parity gate that forces every future feature into the dashboard.

**Source spec:** [docs/design/2026-06-04-server-dashboard-design.md](../2026-06-04-server-dashboard-design.md)

**Architecture:** New `brainpalace-dashboard/` Poetry subpackage = FastAPI BFF (port 8787) that reuses `brainpalace-cli` lifecycle + `config_schema`, proxies per-project servers via httpx, and serves a Vite/React/TS SPA. Project servers keep dynamic ports; dashboard discovers them from `registry.json`.

**Tech stack:** Python 3.12 · FastAPI · uvicorn · httpx · sse-starlette · pytest. Frontend: Vite · React 18 · TypeScript · Tailwind · TanStack Query · TanStack Router · Recharts · Zod · Vitest · Playwright.

---

## Plan files (execute in order)

| # | Plan | Phase(s) | Ships |
|---|------|----------|-------|
| 01 | [scaffold-and-instances](2026-06-04-server-dashboard-01-scaffold-and-instances.md) | 0–1 | Subpackage + InstanceService + lifecycle API (list/start/stop/restart) |
| 02 | [config-schema](2026-06-04-server-dashboard-02-config-schema.md) | 2 | ConfigService + UISchema generator + config GET/PATCH |
| 03 | [proxy-data](2026-06-04-server-dashboard-03-proxy-data.md) | 3 | ProxyService + capabilities + per-instance data/action endpoints |
| 04 | [query-history](2026-06-04-server-dashboard-04-query-history.md) | 4 | Server query-log feature + logs tail + queries API |
| 05 | [spa-foundation](2026-06-04-server-dashboard-05-spa-foundation.md) | 5 | SPA shell + SchemaForm + Overview/Instances/Config tabs |
| 06 | [tabs](2026-06-04-server-dashboard-06-tabs.md) | 6 | Folders/Queries/Jobs/Cache/Graph/Sessions/Logs tabs |
| 07 | [cli-integration](2026-06-04-server-dashboard-07-cli-integration.md) | 7 | `brainpalace dashboard` command + self-lifecycle + docs |
| 08 | [parity-gate](2026-06-04-server-dashboard-08-parity-gate.md) | 8 | Auto-inclusion parity test + `before-push` wiring + governance |
| 09 | [e2e-release](2026-06-04-server-dashboard-09-e2e-release.md) | 9 | Playwright E2E + a11y/polish + release |

Each plan produces working, tested software on its own. Do not start a plan until the previous is green.

---

## Shared conventions (read once, applies to every plan)

**Headless env:** before any Poetry command, export:
```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
```

**Working dir:** repo root `/home/user/VSCode-projects-public/brainpalace` unless a step says otherwise.

**Run dashboard tests:**
```bash
cd brainpalace-dashboard && poetry run pytest -q
```

**Reused CLI symbols (import, do not reimplement):**
- `brainpalace_cli.commands.start`: `read_config(state_dir)`, `read_runtime(state_dir)`, `write_runtime(state_dir, dict)`, `delete_runtime(state_dir)`, `is_process_alive(pid)`, `check_health(base_url, timeout=3.0)`, `find_available_port(host, start, end)`, `update_registry(project_root, state_dir)`.
- `brainpalace_cli.commands.stop`: `wait_for_process_exit(pid, timeout=10.0)`, `remove_from_registry(project_root)`.
- `brainpalace_cli.commands.list_cmd`: `scan_instances() -> list[dict]` (each: `project_root, project_name, base_url, pid, mode, status, started_at`), `get_registry() -> dict`, `save_registry(dict)`.
- `brainpalace_cli.xdg_paths`: `get_xdg_state_dir()`, `get_xdg_config_dir()`, `get_registry_path()`.

**Dashboard durable state:** the dashboard keeps its own `<XDG_STATE>/brainpalace/dashboard_known.json` listing every project it has seen, so **stopped instances stay listed and Start-able even when no server is running**. `registry.json` only tracks *running* servers (pruned on stop); never rely on it for the full project list. The dashboard works with zero servers up — Instances/Overview/Config tabs are server-independent; per-instance data tabs proxy to a live server and show a clean "stopped — Start" state when it's down.
- `brainpalace_cli.config_schema`: `validate_config_dict(config: dict) -> list[ConfigValidationError]`, `ConfigValidationError(field, message, line_number, suggestion)`, and constants `VALID_TOP_LEVEL_KEYS`, `*_KNOWN_FIELDS`, `VALID_*_PROVIDERS`, `VALID_STORAGE_BACKENDS`, `VALID_GRAPHRAG_STORE_TYPES`, `VALID_DOC_EXTRACTORS`, `POSTGRES_KNOWN_FIELDS`, `POSTGRES_TYPE_FIELDS`, `*_TYPE_FIELDS` where present, `_SECTION_SCHEMA`.

> If a reused symbol is module-private or wrapped in Click, the plan's Task 1.0 (in plan 01) refactors `brainpalace-cli` to expose a plain callable — do that refactor, do **not** copy-paste lifecycle logic.

**Project-server REST (proxy targets), base = instance `base_url`:**
- `GET /health/` · `GET /health/status` · `GET /health/providers` · `GET /health/postgres`
- `POST /query/` (body = QueryRequest) · `GET /query/count`
- `GET /folders/` · `DELETE /folders/`
- `POST /index/` · `POST /index/add` · `DELETE /index/`
- `GET /jobs/` · `GET /jobs/{job_id}` · `DELETE /jobs/{job_id}`
- `GET /cache/` · `DELETE /cache/`
- `POST /git/reindex`
- `POST /sessions/reindex` · `POST /sessions/extract` · `POST /sessions/distill`
- `POST /memories/` · `GET /memories/` · `POST /memories/recall` · `DELETE /memories/{id}` · `POST /memories/{id}/obsolete` · `POST /memories/rebuild`
- `GET /context/session-start` · `GET /runtime/`
- `GET /openapi.json` (capabilities)
- **(added in plan 04)** `GET /query/history`, `GET /query/history/{qid}`, `GET /health/logs`

**QueryRequest fields** (server `models/query.py`): `query:str`, `top_k:int(1-50,def5)`, `similarity_threshold:float(0-1,def.3)`, `mode:enum{vector,bm25,hybrid,graph,multi}(def hybrid)`, `alpha:float(0-1,def.5)`, `use_memory:bool`, `time_decay:bool`, `source_types/languages/file_paths/entity_types/relationship_types:list|None`, `language:str|None`.

**Commit style:** conventional commits, one logical change per commit, end body with:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

**Definition of done (every plan):** its tasks checked, its tests green, `task check` green. Do not run `task before-push` until plan 08 exists (it adds the parity gate that earlier plans intentionally don't yet satisfy — until then use `task check` + the plan's pytest target).
