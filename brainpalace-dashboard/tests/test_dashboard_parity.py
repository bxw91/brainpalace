"""Dashboard auto-inclusion parity gate (plan 08).

Three assertions, each importing the LIVE source of truth (config schema,
Click command group, FastAPI app) and diffing it against the checked-in
coverage maps. When a new config field / CLI command / server endpoint is
added without being surfaced in the dashboard (or allowlisted with a reason),
the corresponding test fails. This is wired into ``task before-push`` via the
``lint:dashboard-parity`` target.
"""

from __future__ import annotations

from brainpalace_cli import config_schema as cs

from brainpalace_dashboard.ui_schema import (
    DASHBOARD_HIDDEN_FIELDS,
    OVERRIDES,
    SESSION_ARCHIVE_FIELDS,
    build_ui_schema,
)


def _all_schema_dotpaths() -> set[str]:
    """Every leaf config dotpath the validated schema accepts."""
    paths: set[str] = set()
    section_fields = {
        "embedding": cs.EMBEDDING_KNOWN_FIELDS,
        "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
        "reranker": cs.RERANKER_KNOWN_FIELDS,
        "storage": cs.STORAGE_KNOWN_FIELDS,
        "graphrag": cs.GRAPHRAG_KNOWN_FIELDS,
        "api": cs.API_KNOWN_FIELDS,
        "server": cs.SERVER_KNOWN_FIELDS,
        "project": cs.PROJECT_KNOWN_FIELDS,
        "bm25": cs.BM25_KNOWN_FIELDS,
        "git_indexing": cs.GIT_INDEXING_KNOWN_FIELDS,
        "session_indexing": cs.SESSION_INDEXING_KNOWN_FIELDS,
        "session_extraction": cs.SESSION_EXTRACTION_KNOWN_FIELDS,
    }
    if hasattr(cs, "QUERY_LOG_KNOWN_FIELDS"):
        section_fields["query_log"] = cs.QUERY_LOG_KNOWN_FIELDS
    for sec, fields in section_fields.items():
        for f in fields:
            if sec == "storage" and f == "postgres":
                # nested group; expand to leaves
                for pg in cs.POSTGRES_KNOWN_FIELDS:
                    paths.add(f"storage.postgres.{pg}")
            elif sec == "session_indexing" and f == "archive":
                # nested group (SessionArchiveConfig); expand to leaves
                for a in SESSION_ARCHIVE_FIELDS:
                    paths.add(f"session_indexing.archive.{a}")
            else:
                paths.add(f"{sec}.{f}")
    return paths


def _rendered_dotpaths() -> set[str]:
    """Every dotpath the dashboard UISchema actually renders as a control."""
    ui = build_ui_schema()
    out: set[str] = set()
    for sec in ui["sections"]:
        for fld in sec["fields"]:
            if fld["widget"] == "group":
                for child in fld.get("fields", []):
                    out.add(child["dotpath"])
            else:
                out.add(fld["dotpath"])
    return out


# --------------------------------------------------------------------------- #
# Config parity
# --------------------------------------------------------------------------- #
def test_every_config_field_surfaced_or_hidden() -> None:
    missing = (
        _all_schema_dotpaths() - _rendered_dotpaths() - set(DASHBOARD_HIDDEN_FIELDS)
    )
    assert not missing, (
        "Config fields not surfaced in the dashboard and not in "
        f"DASHBOARD_HIDDEN_FIELDS: {sorted(missing)}. Add them to the UISchema "
        "or to DASHBOARD_HIDDEN_FIELDS with a reason."
    )


def test_no_stale_overrides() -> None:
    valid = _all_schema_dotpaths() | {"storage.postgres", "session_indexing.archive"}
    stale = {
        k
        for k in OVERRIDES
        if k not in valid
        and not k.startswith("storage.postgres.")
        and not k.startswith("session_indexing.archive.")
    }
    assert not stale, f"OVERRIDES reference unknown config fields: {sorted(stale)}"


def test_no_stale_hidden_fields() -> None:
    valid = _all_schema_dotpaths()
    stale = {k for k in DASHBOARD_HIDDEN_FIELDS if k not in valid}
    assert not stale, (
        "DASHBOARD_HIDDEN_FIELDS lists unknown config fields: " f"{sorted(stale)}"
    )


# --------------------------------------------------------------------------- #
# CLI parity
# --------------------------------------------------------------------------- #
def test_every_cli_command_classified() -> None:
    from brainpalace_cli.cli import cli  # live Click group

    from brainpalace_dashboard.coverage_maps import CLI_DASHBOARD_COVERAGE

    registered = set(cli.commands.keys())
    unclassified = registered - set(CLI_DASHBOARD_COVERAGE)
    assert not unclassified, (
        f"CLI commands not classified for the dashboard: {sorted(unclassified)}. "
        "Map each to a tab/action or 'cli_only: <reason>' in "
        "coverage_maps.CLI_DASHBOARD_COVERAGE."
    )
    removed = set(CLI_DASHBOARD_COVERAGE) - registered
    assert not removed, f"coverage_maps lists removed CLI commands: {sorted(removed)}"


# --------------------------------------------------------------------------- #
# Endpoint parity
# --------------------------------------------------------------------------- #
# Project-server route prefixes the dashboard proxies / depends on. Routes
# outside these prefixes (docs, openapi, root) are not dashboard surfaces.
_DASHBOARD_ROUTE_PREFIXES = (
    "/health",
    "/query",
    "/folders",
    "/index",
    "/jobs",
    "/cache",
    "/git",
    "/graph",
    "/sessions",
    "/memories",
    "/context",
    "/runtime",
)


def _live_dashboard_routes() -> set[str]:
    from brainpalace_server.api.main import app

    live: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path and path.startswith(_DASHBOARD_ROUTE_PREFIXES):
            live.add(path)
    return live


def test_every_server_endpoint_classified() -> None:
    from brainpalace_dashboard.coverage_maps import ENDPOINT_SURFACES

    live = _live_dashboard_routes()
    unclassified = live - set(ENDPOINT_SURFACES)
    assert not unclassified, (
        f"Server endpoints not classified for the dashboard: {sorted(unclassified)}. "
        "Map each to a tab or 'unsurfaced: <reason>' in "
        "coverage_maps.ENDPOINT_SURFACES (match the exact live route.path)."
    )
    removed = set(ENDPOINT_SURFACES) - live
    assert not removed, f"ENDPOINT_SURFACES lists removed routes: {sorted(removed)}"
