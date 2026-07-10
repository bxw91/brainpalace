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

from brainpalace_dashboard import model_introspect as mi
from brainpalace_dashboard.ui_schema import (
    DASHBOARD_HIDDEN_FIELDS,
    OVERRIDES,
    build_ui_schema,
)

# All config sections are now model-backed (bind→BindConfig, server→ServerConfig,
# the rest via their pydantic models). No modelless sections remain.
_MODELLESS: dict[str, set[str]] = {}


def _all_schema_dotpaths() -> set[str]:
    """Every leaf config dotpath, sourced from the SINGLE SOURCE — the pydantic
    models — plus the model-less runtime/identity sections.

    This is what makes add/remove automatic: the gate compares what the models
    declare against what the dashboard renders, so a field added to a model must
    be surfaced or explicitly hidden, and a removed one cannot linger.
    """
    paths: set[str] = set()
    for sec, model in mi.SECTION_MODELS.items():
        for f in model.model_fields:
            dotpath = f"{sec}.{f}"
            if dotpath == "storage.postgres":
                # raw dict (no nested model); leaves come from config_schema
                for pg in cs.POSTGRES_KNOWN_FIELDS:
                    paths.add(f"storage.postgres.{pg}")
            elif dotpath == "session_indexing.archive":
                # nested model (SessionArchiveConfig); expand to leaves
                for a in mi.nested_field_names("session_indexing.archive"):
                    paths.add(f"session_indexing.archive.{a}")
            else:
                paths.add(dotpath)
    for sec, fields in _MODELLESS.items():
        for f in fields:
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


def test_widget_and_default_derive_from_the_model() -> None:
    """No drift: every rendered model-backed field's widget/default/options is
    exactly what the pydantic model yields (modulo the documented fallbacks).

    Structurally a new bool can never silently render as a text box, because the
    form reads the model — this asserts that contract end-to-end.
    """
    from brainpalace_dashboard.ui_schema import (
        DEFAULT_FALLBACKS,
        ENUM_FALLBACKS,
    )

    ui = build_ui_schema()
    for sec in ui["sections"]:
        # Map a rendered section back to its model section key. The archive is
        # rendered as its own section but its fields belong to the nested model.
        for fld in sec["fields"]:
            if fld.get("widget") == "group":
                continue
            dotpath = fld["dotpath"]
            section, _, key = dotpath.rpartition(".")
            if section in mi.SECTION_MODELS:
                derived = mi.derive_field(section, key)
            elif section == "session_indexing.archive":
                derived = mi.nested_field("session_indexing.archive", key)
            else:
                continue  # model-less / postgres handled elsewhere
            # widget: model wins unless an ENUM_FALLBACK promotes a plain-str field
            expected_widget = "enum" if dotpath in ENUM_FALLBACKS else derived["widget"]
            assert fld["widget"] == expected_widget, dotpath
            # default: model value unless a settings-sourced fallback overrides
            expected_default = DEFAULT_FALLBACKS.get(dotpath, derived.get("default"))
            assert fld.get("default") == expected_default, dotpath


def test_overrides_are_presentation_only() -> None:
    """OVERRIDES must never carry widget/default/options — those derive from the
    model. (Labels, help, placeholders, presets, visibility, secret are fine.)"""
    forbidden = {"widget", "default", "options"}
    offenders = {
        k: sorted(set(v) & forbidden)
        for k, v in OVERRIDES.items()
        if set(v) & forbidden
    }
    assert not offenders, f"OVERRIDES must stay presentational: {offenders}"


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
    "/records",
    "/references",
    "/extraction",
    "/metrics",
    "/ingest",
    "/entities",
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


def test_readonly_fields_valid_and_not_hidden() -> None:
    from brainpalace_dashboard.ui_schema import (
        DASHBOARD_HIDDEN_FIELDS,
        DASHBOARD_READONLY_FIELDS,
    )

    valid = _all_schema_dotpaths()
    stale = {k for k in DASHBOARD_READONLY_FIELDS if k not in valid}
    assert not stale, f"DASHBOARD_READONLY_FIELDS lists unknown fields: {sorted(stale)}"
    # A field is read-only XOR hidden — never both.
    overlap = set(DASHBOARD_READONLY_FIELDS) & set(DASHBOARD_HIDDEN_FIELDS)
    assert not overlap, f"fields both hidden and read-only: {sorted(overlap)}"
    # Every read-only field must have a non-empty reason.
    assert all(DASHBOARD_READONLY_FIELDS.values())


def test_dashboard_fields_are_in_registry_or_allowlisted() -> None:
    """Every top-level field the dashboard renders is sourced from the CLI field
    registry (FIELD_SPECS) or explicitly allowlisted (hidden/read-only/the raw
    postgres group). Guards the registry as the single source for the form."""
    from brainpalace_cli import config_fields as cf

    from brainpalace_dashboard.ui_schema import (
        DASHBOARD_HIDDEN_FIELDS,
        DASHBOARD_READONLY_FIELDS,
        build_ui_schema,
    )

    # All sections are model-backed now; nothing relies on a modelless fallback.
    modelless: set[str] = set()
    for section in build_ui_schema()["sections"]:
        for field in section["fields"]:
            if field.get("widget") == "group":
                continue  # storage.postgres raw dict — not model-backed
            dp = field["dotpath"]
            assert (
                dp in cf.FIELD_SPECS
                or dp in DASHBOARD_HIDDEN_FIELDS
                or dp in DASHBOARD_READONLY_FIELDS
                or dp.split(".")[0] in modelless
            ), dp


def test_group_order_equals_section_order() -> None:
    from brainpalace_cli import config_fields as cf

    from brainpalace_dashboard.ui_schema import SECTION_ORDER

    assert cf.GROUP_ORDER == SECTION_ORDER
