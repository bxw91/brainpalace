# Dashboard Plan 08 — Auto-inclusion parity gate + governance

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–07. **This plan operationalizes the core meta-requirement:** every future config option / CLI command / server endpoint / displayable datum must surface in the dashboard, enforced before release.

**Goal:** A `lint:dashboard-parity` test wired into `task before-push` that fails when a config field, CLI command, or server endpoint is added without being surfaced in the dashboard (or explicitly allowlisted with a reason). Plus governance: a `CLAUDE.md` "Dashboard parity" rule and a `docs/RELEASING.md` pre-release step.

**Architecture:** Three parity assertions, each backed by a checked-in coverage map with reasons. The test imports the live `config_schema`, the live CLI command registry, and a checked-in `ENDPOINT_SURFACES` manifest (the canonical list of project-server routes), and diffs them against the dashboard's coverage.

**Tech Stack:** pytest, Taskfile.

---

## File Structure
- Create `brainpalace-dashboard/brainpalace_dashboard/coverage_maps.py` — `ENDPOINT_SURFACES`, `CLI_DASHBOARD_COVERAGE`, re-exports `DASHBOARD_HIDDEN_FIELDS`.
- Create `brainpalace-dashboard/tests/test_dashboard_parity.py` — the gate.
- Modify `Taskfile.yml` — `lint:dashboard-parity` + add to `before-push`.
- Modify `CLAUDE.md` — "Dashboard parity" rule.
- Modify `docs/RELEASING.md` + `docs/DEVELOPERS_GUIDE.md` — pre-release step + rule detail.

---

### Task 8.1: Coverage maps (the allowlists with reasons)

**Files:** Create `brainpalace_dashboard/coverage_maps.py`.

- [ ] **Step 1: Write the maps**

```python
# brainpalace-dashboard/brainpalace_dashboard/coverage_maps.py
"""Canonical coverage maps for the dashboard parity gate (plan 08).

Adding a config field / CLI command / server endpoint forces an update here
(or it shows up automatically) — the parity test fails otherwise.
"""

from __future__ import annotations

# Every project-server route prefix -> the dashboard tab that surfaces it,
# or "unsurfaced:<reason>" for deliberate exclusions.
ENDPOINT_SURFACES: dict[str, str] = {
    "/health/": "Overview/Instances",
    "/health/status": "Overview/Graph/Sessions",
    "/health/providers": "Config/Overview",
    "/health/postgres": "unsurfaced: backend health detail, low user value (shown via providers)",
    "/health/logs": "Logs",
    "/query/": "Queries (replay)",
    "/query/count": "Overview",
    "/query/history": "Queries",
    "/query/history/{qid}": "Queries (drawer)",
    "/folders/": "Folders",
    "/index/": "Folders (add)",
    "/index/add": "Folders (add)",
    "/jobs/": "Jobs",
    "/jobs/{job_id}": "Jobs",
    "/cache/": "Cache",
    "/git/reindex": "Graph",
    "/sessions/reindex": "Sessions",
    "/sessions/extract": "unsurfaced: written by AI-session hooks, not a dashboard action",
    "/sessions/distill": "unsurfaced: written by AI-session hooks, not a dashboard action",
    "/memories/": "Sessions",
    "/memories/recall": "unsurfaced: retrieval primitive, covered by query replay",
    "/memories/{memory_id}/obsolete": "Sessions",
    "/memories/rebuild": "Sessions",
    "/context/session-start": "unsurfaced: agent context block, not user-facing",
    "/runtime/": "Instances (id/url shown)",
}

# Every CLI command -> "tab/action" it maps to, or "cli_only: <reason>".
CLI_DASHBOARD_COVERAGE: dict[str, str] = {
    "init": "cli_only: project bootstrap; dashboard manages existing projects only",
    "start": "Instances (Start)",
    "stop": "Instances (Stop)",
    "list": "Instances",
    "whoami": "cli_only: CWD-context helper, irrelevant in a fleet UI",
    "doctor": "cli_only: local diagnostics CLI",
    "status": "Overview/Instances",
    "query": "Queries (replay)",
    "remember": "Sessions (memories)",
    "recall": "Queries (replay)/Sessions",
    "memories": "Sessions",
    "context": "cli_only: agent context block",
    "submit-session": "cli_only: AI-session hook entrypoint",
    "index": "Folders",
    "inject": "cli_only: scripted enrichment, advanced",
    "jobs": "Jobs",
    "reset": "Folders (Reset index)",
    "config": "Config",
    "folders": "Folders",
    "types": "Folders (type presets)",
    "cache": "Cache",
    "uninstall": "cli_only: package management",
    "update": "cli_only: package management",
    "install-agent": "cli_only: runtime plugin install",
    "install-session-hooks": "cli_only: hook install",
    "backfill-sessions": "cli_only: one-off maintenance",
    "drain-queue": "Jobs",
    "mcp": "cli_only: stdio MCP transport, not a UI surface",
    "dashboard": "cli_only: launches the dashboard itself",
}
```

- [ ] **Step 2: Commit** (`feat(dashboard): parity coverage maps`).

---

### Task 8.2: Config parity assertion

**Files:** Create/extend `tests/test_dashboard_parity.py`.

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_dashboard_parity.py
import pytest
from brainpalace_cli import config_schema as cs
from brainpalace_dashboard.ui_schema import build_ui_schema, DASHBOARD_HIDDEN_FIELDS, OVERRIDES


def _all_schema_dotpaths() -> set[str]:
    paths = set()
    section_fields = {
        "embedding": cs.EMBEDDING_KNOWN_FIELDS, "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
        "reranker": cs.RERANKER_KNOWN_FIELDS, "storage": cs.STORAGE_KNOWN_FIELDS,
        "graphrag": cs.GRAPHRAG_KNOWN_FIELDS, "api": cs.API_KNOWN_FIELDS,
        "server": cs.SERVER_KNOWN_FIELDS, "project": cs.PROJECT_KNOWN_FIELDS,
    }
    if hasattr(cs, "QUERY_LOG_KNOWN_FIELDS"):
        section_fields["query_log"] = cs.QUERY_LOG_KNOWN_FIELDS
    for sec, fields in section_fields.items():
        for f in fields:
            if f == "postgres":   # nested group; expand
                for pg in cs.POSTGRES_KNOWN_FIELDS:
                    paths.add(f"storage.postgres.{pg}")
            else:
                paths.add(f"{sec}.{f}")
    return paths


def _rendered_dotpaths() -> set[str]:
    ui = build_ui_schema()
    out = set()
    for sec in ui["sections"]:
        for fld in sec["fields"]:
            if fld["widget"] == "group":
                for child in fld.get("fields", []):
                    out.add(child["dotpath"])
            else:
                out.add(fld["dotpath"])
    return out


def test_every_config_field_surfaced_or_hidden():
    missing = _all_schema_dotpaths() - _rendered_dotpaths() - set(DASHBOARD_HIDDEN_FIELDS)
    assert not missing, (
        "Config fields not surfaced in the dashboard and not in DASHBOARD_HIDDEN_FIELDS: "
        f"{sorted(missing)}. Add them to the UISchema or DASHBOARD_HIDDEN_FIELDS with a reason."
    )


def test_no_stale_overrides():
    valid = _all_schema_dotpaths() | {"storage.postgres"}
    stale = {k for k in OVERRIDES if k not in valid and not k.startswith("storage.postgres.")}
    assert not stale, f"OVERRIDES reference unknown config fields: {sorted(stale)}"
```

- [ ] **Step 2: Run → PASS** (the dashboard already renders all fields). If it fails, fix the UISchema or the hidden allowlist — that is the gate doing its job.
- [ ] **Step 3: Commit** (`test(dashboard): config parity assertion`).

---

### Task 8.3: CLI parity assertion

**Files:** Extend `tests/test_dashboard_parity.py`.

- [ ] **Step 1: Write the failing test**

```python
def test_every_cli_command_classified():
    from brainpalace_cli.cli import cli  # Click group
    from brainpalace_dashboard.coverage_maps import CLI_DASHBOARD_COVERAGE
    registered = set(cli.commands.keys())
    unclassified = registered - set(CLI_DASHBOARD_COVERAGE)
    assert not unclassified, (
        f"CLI commands not classified for the dashboard: {sorted(unclassified)}. "
        "Map each to a tab/action or 'cli_only: <reason>' in coverage_maps.CLI_DASHBOARD_COVERAGE."
    )
    # And no rotting entries:
    removed = set(CLI_DASHBOARD_COVERAGE) - registered
    assert not removed, f"coverage_maps lists removed CLI commands: {sorted(removed)}"
```

- [ ] **Step 2: Run → PASS** (Task 8.1 map already lists every command). **Step 3: Commit** (`test(dashboard): CLI parity assertion`).

---

### Task 8.4: Endpoint parity assertion

**Files:** Extend `tests/test_dashboard_parity.py`.

- [ ] **Step 1: Write the failing test** — derive the live route list from the server app and diff against `ENDPOINT_SURFACES`:

```python
def test_every_server_endpoint_classified():
    from brainpalace_server.api.main import app
    from brainpalace_dashboard.coverage_maps import ENDPOINT_SURFACES
    live = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path and (path.startswith("/health") or path.startswith("/query")
                     or path.startswith("/folders") or path.startswith("/index")
                     or path.startswith("/jobs") or path.startswith("/cache")
                     or path.startswith("/git") or path.startswith("/sessions")
                     or path.startswith("/memories") or path.startswith("/context")
                     or path.startswith("/runtime")):
            live.add(path)
    unclassified = live - set(ENDPOINT_SURFACES)
    assert not unclassified, (
        f"Server endpoints not classified for the dashboard: {sorted(unclassified)}. "
        "Map each to a tab or 'unsurfaced: <reason>' in coverage_maps.ENDPOINT_SURFACES."
    )
    removed = set(ENDPOINT_SURFACES) - live
    assert not removed, f"ENDPOINT_SURFACES lists removed routes: {sorted(removed)}"
```

- [ ] **Step 2: Run → reconcile.** Run it; for any path the server exposes that the map omits, add it to `ENDPOINT_SURFACES` (tab or `unsurfaced: reason`). For any map key the server no longer exposes, remove it. Iterate until green. (FastAPI route paths use `{param}` form — make `ENDPOINT_SURFACES` keys match the live `route.path` exactly; adjust the literal keys in Task 8.1 to whatever the server actually reports.)
- [ ] **Step 3: Commit** (`test(dashboard): endpoint parity assertion`).

---

### Task 8.5: Wire into Taskfile `before-push`

**Files:** Modify `Taskfile.yml`.

- [ ] **Step 1:** Add a task:

```yaml
  lint:dashboard-parity:
    desc: "Fail if a config/CLI/endpoint is not surfaced in the dashboard"
    cmds:
      - cd brainpalace-dashboard && poetry run pytest tests/test_dashboard_parity.py -q
```

- [ ] **Step 2:** Add `lint:dashboard-parity` to the `before-push` task's dependency/command list (mirror how `lint:doc-freshness` is wired).
- [ ] **Step 3: Run** `task lint:dashboard-parity` → PASS, then `task before-push` → PASS (or fix whatever it surfaces).
- [ ] **Step 4: Commit** (`build: add dashboard-parity to before-push gate`).

---

### Task 8.6: Governance — CLAUDE.md rule + RELEASING step

**Files:** Modify `CLAUDE.md`, `docs/RELEASING.md`, `docs/DEVELOPERS_GUIDE.md`.

- [ ] **Step 1: `CLAUDE.md`** — add a new top-level section mirroring "Setup-surface parity":

```markdown
## Dashboard parity — surface every feature (MANDATORY)

When you add a **config option**, **CLI command**, **server endpoint**, or any
**user-facing datum**, you MUST surface it in the control-plane dashboard in the
same change — or add it to the relevant allowlist in
`brainpalace-dashboard/brainpalace_dashboard/coverage_maps.py`
(`ENDPOINT_SURFACES` / `CLI_DASHBOARD_COVERAGE`) or `ui_schema.DASHBOARD_HIDDEN_FIELDS`
with a one-line reason. Config fields auto-render from `config_schema`; CLI commands
and endpoints are checked by `lint:dashboard-parity` in `task before-push`. Note the
change in `docs/CHANGELOG.md`. Full rule:
[docs/DEVELOPERS_GUIDE.md → Dashboard parity](docs/DEVELOPERS_GUIDE.md#dashboard-parity).
```

- [ ] **Step 2: `docs/DEVELOPERS_GUIDE.md`** — add a "Dashboard parity" subsection detailing the three checks, the coverage-map files, and how to satisfy each (render vs allowlist). Bump its `last_validated`.
- [ ] **Step 3: `docs/RELEASING.md`** — add a pre-release checklist line: "☐ `task before-push` green (includes `lint:dashboard-parity`) — every new config/CLI/endpoint is surfaced in the dashboard or allowlisted." Bump `last_validated`.
- [ ] **Step 4: Run** `task lint:doc-freshness` → PASS.
- [ ] **Step 5: Commit** (`docs: dashboard parity governance (CLAUDE.md + RELEASING)`).

---

## Plan 08 self-check
- [ ] Adding a dummy config field (temporarily) makes `test_every_config_field_surfaced_or_hidden` fail; adding a dummy CLI command makes the CLI test fail; adding a dummy server route makes the endpoint test fail. Revert the dummies after confirming.
- [ ] `task before-push` runs `lint:dashboard-parity` and is green on the real tree.
- [ ] CLAUDE.md + DEVELOPERS_GUIDE + RELEASING document the rule.
