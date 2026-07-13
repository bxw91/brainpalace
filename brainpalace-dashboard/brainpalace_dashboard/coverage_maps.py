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
    "/health/providers/test": "Config (provider connectivity test)",
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
    "/query/stats": "Queries (analytics panel)",
    # --- index data ops (nested under /index/ on the project server) ---
    "/index/": "Folders (add / reset index)",
    "/index/add": "Folders (add)",
    "/index/folders/": "Folders (list / remove)",
    "/index/cache": "Cache",
    "/index/cache/": "Cache (clear)",
    "/index/cache/history": "Cache (hit-rate trend)",
    "/index/cache/economics": "Cache (cost estimate)",
    "/index/jobs/": "Jobs (list)",
    "/index/jobs/{job_id}": "Jobs (detail / cancel)",
    "/index/jobs/{job_id}/approve": "Jobs (approve blocked job)",
    "/index/documents": "Documents (file browser)",
    "/index/documents/chunks": "Documents (chunk drawer)",
    "/index/fingerprint": (
        "unsurfaced: read-only index identity consumed by the Config save "
        "data-compatibility guard, not a standalone control"
    ),
    "/index/estimate": (
        "unsurfaced: dry-run embedding-token advisory for the CLI/init "
        "pre-index prompt, not a dashboard action"
    ),
    # --- graph ---
    "/git/reindex": "Graph (rebuild)",
    "/graph/nodes": "Graph (browser search)",
    "/graph/top": "Graph (browser start — top hubs)",
    "/graph/neighbors": "Graph (browser expand)",
    "/graph/node/source": "Graph (detail panel — lazy source snippet)",
    "/graph/path": (
        "unsurfaced: pairwise node-picker UX deferred; "
        "served via `brainpalace graph path` (CLI)"
    ),
    "/graph/impact": "Graph (detail panel — impact)",
    "/graph/cochange": "Graph (detail panel — co-change)",
    # --- sessions ---
    "/sessions/reindex": "Sessions (re-index)",
    "/sessions/archive": "Sessions (archive browser)",
    "/sessions/decisions": "Sessions (decision browser)",
    "/sessions/timeline": "Sessions (decision timeline)",
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
    # --- records (compute mode) ---
    "/records/stats": (
        "unsurfaced: record-store statistics for CLI/compute mode; "
        "no dashboard panel yet"
    ),
    "/records/revalidate": (
        "unsurfaced: maintenance action (re-score low-confidence records); "
        "CLI-driven, no dashboard panel yet"
    ),
    "/records/recompute-salience": (
        "unsurfaced: maintenance action (re-score salience column); "
        "CLI-driven, no dashboard panel yet"
    ),
    "/extraction/pending": (
        "unsurfaced: AI-drain queue selector, consumed by the CC drain command, "
        "not a dashboard action"
    ),
    "/extraction/submit": (
        "unsurfaced: AI-drain submit (triplets/session), not a dashboard action"
    ),
    "/extraction/text/{chunk_id}": (
        "unsurfaced: id-based chunk text fetch for the subagent executor, "
        "not a dashboard action"
    ),
    "/metrics/usage": "Usage (telemetry tab)",
    # --- text ingest (spec Item 3) ---
    "/ingest/text": (
        "unsurfaced: programmatic text-ingest with caller provenance, driven by "
        "the `brainpalace ingest` CLI / in-process adapters; no dashboard panel yet"
    ),
    "/ingest/sources": (
        "unsurfaced: enumerate distinct ingested source_ids with provenance + "
        "chunk counts, driven by `brainpalace ingest sources`; no dashboard panel yet"
    ),
    "/ingest/text/{source_id}": (
        "unsurfaced: un-ingest a source_id (DELETE, `brainpalace ingest --delete`) "
        "and list its chunks (GET, `brainpalace ingest show`); no dashboard panel yet"
    ),
    "/ingest/source/{source_id}": (
        "unsurfaced: full forget (chunks + records + references cascade) for "
        "a source_id, driven by `brainpalace ingest --forget`; no dashboard "
        "panel yet"
    ),
    "/ingest/records": (
        "unsurfaced: HTTP write of caller-asserted typed records, driven by "
        "`brainpalace ingest record` / in-process adapters; no dashboard panel yet"
    ),
    "/ingest/references": (
        "unsurfaced: HTTP write of lazy-tier references, driven by "
        "`brainpalace ingest reference` / in-process adapters; no dashboard panel yet"
    ),
    # --- reference catalog (Round 2 Plan C) ---
    "/references": (
        "unsurfaced: reference-catalog listing, driven by the "
        "`brainpalace references` CLI; no dashboard panel yet"
    ),
    "/references/search": (
        "unsurfaced: semantic search over reference summaries, driven by "
        "`brainpalace references search`; no dashboard panel yet"
    ),
    "/references/embed-missing": (
        "unsurfaced: backfill reference summary embeddings, driven by "
        "`brainpalace references embed-missing`; no dashboard panel yet"
    ),
    # --- identity store (G5): person / alias / link ---
    "/entities/person": (
        "unsurfaced: identity upsert (also the EmittedEntity sink), driven by "
        "`brainpalace entities person` / in-process ingest; no dashboard panel yet"
    ),
    "/entities/alias": (
        "unsurfaced: bind a surface to a person, driven by "
        "`brainpalace entities alias`; no dashboard panel yet"
    ),
    "/entities/link": (
        "unsurfaced: attach a ref to a person / record it unresolved, driven by "
        "`brainpalace entities link`; no dashboard panel yet"
    ),
    "/entities/link/{link_id}": (
        "unsurfaced: retract a link, driven by the entities API; "
        "no dashboard panel yet"
    ),
    "/entities/resolve": (
        "unsurfaced: ranked identity candidates (engine never picks), driven by "
        "`brainpalace entities resolve`; no dashboard panel yet"
    ),
    "/entities/unresolved": (
        "unsurfaced: the unresolved-link bucket, driven by "
        "`brainpalace entities unresolved`; no dashboard panel yet"
    ),
    "/entities/backfill": (
        "unsurfaced: re-score unresolved links against current aliases, driven by "
        "`brainpalace entities backfill`; no dashboard panel yet"
    ),
    # --- rehome (fail-closed move quarantine, Plan 05) ---
    "/rehome/": (
        "unsurfaced: rehome/quarantine status, served even under quarantine; "
        "surfaced via `brainpalace rehome` (CLI) — a quarantined server 503s the "
        "dashboard's proxied API, so no dashboard panel"
    ),
    "/rehome/resume": (
        "unsurfaced: resume a pending/failed rehome; driven by "
        "`brainpalace rehome --resume` (CLI); no dashboard panel"
    ),
}

# Every CLI command -> "tab/action" it maps to, or "cli_only: <reason>".
# Keys MUST match the live ``brainpalace_cli.cli.cli.commands`` exactly.
CLI_DASHBOARD_COVERAGE: dict[str, str] = {
    "ai-guide": "cli_only: prints AI usage guidance for agents, not a UI surface",
    "backfill-sessions": "cli_only: one-off maintenance script",
    "cache": "Cache",
    "config": "Config",
    "context": "cli_only: agent context block, not user-facing",
    "dashboard": "cli_only: launches the dashboard itself",
    "doctor": "cli_only: local diagnostics CLI",
    "entities": (
        "cli_only: identity person/alias/link management + candidate resolution; "
        "no dashboard panel yet"
    ),
    "extraction": "cli_only: AI subagent extraction executor, not a UI surface",
    "dump-interface": "cli_only: hidden doc-sync introspection, not a UI surface",
    "folders": "Folders",
    "graph": "Graph",
    "hook": "cli_only: internal hook dispatcher, not a user command",
    "index": "Folders",
    "ingest": "cli_only: scripted text ingest, advanced",
    "init": ("cli_only: project bootstrap; dashboard manages existing projects only"),
    "inject": "cli_only: scripted enrichment, advanced",
    "install-agent": "cli_only: runtime plugin install",
    "install-session-hooks": "cli_only: hook install",
    "jobs": "Jobs",
    "list": "Instances",
    "lsp": "cli_only: local-machine mutation, not a control-plane action",
    "mcp": "cli_only: stdio MCP transport, not a UI surface",
    "memories": "Sessions",
    "plugin": "cli_only: Claude Code plugin management",
    # NOTE: this gate classifies whole commands (keys MUST match a live Click
    # command name exactly), not individual flags. `query --include-sensitive`
    # (sensitivity enforcement, Phase 7) is a flag-level carve-out under the
    # already-classified `query` command below, not a separate map entry: it
    # is cli_only by design — the dashboard's /replay proxy never forwards
    # `include_sensitive` (see tests/test_replay_omits_sensitive.py) because
    # the dashboard is a shared surface that must never reveal
    # sensitivity-marked rows.
    "query": "Queries (replay)",
    "read-only": "Config (server.read_only toggle + Overview read-only banner)",
    "recall": "Queries (replay) / Sessions",
    "rehome": (
        "cli_only: fail-closed project-move recovery. A quarantined server 503s the "
        "dashboard's own proxied API, so recovery is inherently CLI/restart-driven; "
        "no dashboard panel."
    ),
    "remember": "Sessions (memories)",
    "reset": "Folders (Reset index)",
    "session-path": ("cli_only: prints session-archive path, scripting helper"),
    "start": "Instances (Start)",
    "status": "Overview/Instances",
    "stop": "Instances (Stop)",
    "submit-session": "cli_only: AI-session hook entrypoint",
    "sync-docs": "cli_only: hidden interface doc-sync gate, not a UI surface",
    "types": "Folders (type presets)",
    "uninstall": "cli_only: package management",
    "update": "cli_only: package management",
    "verify-docs": (
        "cli_only: hidden Layer-B doc-verification machinery (resolve/record), "
        "agent-driven + repo-only, not a UI surface"
    ),
    "whoami": "cli_only: CWD-context helper, irrelevant in a fleet UI",
    "records": ("cli_only: record store stats/revalidate; no dashboard panel yet"),
    "references": (
        "cli_only: reference catalog list/search/resolve/embed-missing; "
        "no dashboard panel yet"
    ),
    "rules": (
        "cli_only: taught confidence rules list/add/retire; " "no dashboard panel yet"
    ),
}
