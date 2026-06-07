"""Canonical coverage maps for the dashboard parity gate (plan 08).

Adding a config field / CLI command / server endpoint forces an update here
(or it shows up automatically) — the parity test fails otherwise.

The three allowlists below are the ONLY checked-in snapshots; every entry that
is *not* surfaced in the dashboard carries a one-line reason. The parity tests
in ``tests/test_dashboard_parity.py`` import the live config schema, the live
Click command group, and the live FastAPI app and diff them against these maps,
so they cannot drift silently.

Endpoint paths use the EXACT ``route.path`` form reported by
``brainpalace_server.api.main.app`` (FastAPI ``{param}`` syntax for path
parameters). The data routes are nested under ``/index/`` on the project
server; the dashboard's ProxyService targets those exact paths.
"""

from __future__ import annotations

from brainpalace_dashboard.ui_schema import DASHBOARD_HIDDEN_FIELDS

__all__ = [
    "ENDPOINT_SURFACES",
    "CLI_DASHBOARD_COVERAGE",
    "DASHBOARD_HIDDEN_FIELDS",
]

# Every project-server route the dashboard cares about -> the dashboard tab that
# surfaces it, or "unsurfaced: <reason>" for deliberate exclusions.
# Keys MUST match the live ``route.path`` exactly (verified against
# brainpalace_server.api.main.app).
ENDPOINT_SURFACES: dict[str, str] = {
    # --- health ---
    "/health/": "Overview/Instances (health ping)",
    "/health/status": "Overview/Graph/Sessions (feature status)",
    "/health/providers": "Config/Overview (provider readiness)",
    "/health/postgres": (
        "unsurfaced: backend health detail, low user value "
        "(surfaced indirectly via providers/status)"
    ),
    "/health/logs": "Logs",
    # --- query ---
    "/query/": "Queries (replay)",
    "/query/count": "Overview (chunk count)",
    "/query/history": "Queries (history list)",
    "/query/history/{qid}": "Queries (drawer detail)",
    # --- index data ops (nested under /index/ on the project server) ---
    "/index/": "Folders (add / reset index)",
    "/index/add": "Folders (add)",
    "/index/folders/": "Folders (list / remove)",
    "/index/cache": "Cache",
    "/index/cache/": "Cache (clear)",
    "/index/jobs/": "Jobs (list)",
    "/index/jobs/{job_id}": "Jobs (detail / cancel)",
    # --- graph ---
    "/git/reindex": "Graph (rebuild)",
    # --- sessions ---
    "/sessions/reindex": "Sessions (re-index)",
    "/sessions/extract": (
        "unsurfaced: written by AI-session hooks, not a dashboard action"
    ),
    "/sessions/distill": (
        "unsurfaced: written by AI-session hooks, not a dashboard action"
    ),
    # --- memories ---
    "/memories/": "Sessions (curated memories)",
    "/memories/recall": ("unsurfaced: retrieval primitive, covered by query replay"),
    "/memories/rebuild": "Sessions (rebuild memories)",
    "/memories/{memory_id}": "Sessions (delete memory)",
    "/memories/{memory_id}/obsolete": "Sessions (mark obsolete)",
    # --- context / runtime ---
    "/context/session-start": ("unsurfaced: agent context block, not user-facing"),
    "/runtime/": "Instances (id / url shown)",
}

# Every CLI command -> "tab/action" it maps to, or "cli_only: <reason>".
# Keys MUST match the live ``brainpalace_cli.cli.cli.commands`` exactly.
CLI_DASHBOARD_COVERAGE: dict[str, str] = {
    "backfill-sessions": "cli_only: one-off maintenance script",
    "cache": "Cache",
    "config": "Config",
    "context": "cli_only: agent context block, not user-facing",
    "dashboard": "cli_only: launches the dashboard itself",
    "doctor": "cli_only: local diagnostics CLI",
    "drain-queue": "Jobs (queue drains via job worker)",
    "drain-tick": ("cli_only: single job-worker tick, internal scheduler hook"),
    "folders": "Folders",
    "index": "Folders",
    "init": ("cli_only: project bootstrap; dashboard manages existing projects only"),
    "inject": "cli_only: scripted enrichment, advanced",
    "install-agent": "cli_only: runtime plugin install",
    "install-session-hooks": "cli_only: hook install",
    "jobs": "Jobs",
    "list": "Instances",
    "mcp": "cli_only: stdio MCP transport, not a UI surface",
    "memories": "Sessions",
    "plugin": "cli_only: Claude Code plugin management",
    "query": "Queries (replay)",
    "recall": "Queries (replay) / Sessions",
    "remember": "Sessions (memories)",
    "reset": "Folders (Reset index)",
    "session-path": ("cli_only: prints session-archive path, scripting helper"),
    "start": "Instances (Start)",
    "status": "Overview/Instances",
    "stop": "Instances (Stop)",
    "submit-session": "cli_only: AI-session hook entrypoint",
    "types": "Folders (type presets)",
    "uninstall": "cli_only: package management",
    "update": "cli_only: package management",
    "whoami": "cli_only: CWD-context helper, irrelevant in a fleet UI",
}
