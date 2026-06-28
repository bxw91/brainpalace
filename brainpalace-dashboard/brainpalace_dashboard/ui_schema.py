"""Generate a UI form schema from the config models (single source of truth).

Every known config field renders automatically. Field ORDER, LABEL, and HELP
come from the CLI field registry (``brainpalace_cli.config_fields``); the local
OVERRIDES dict only carries the values the registry does not own (presets,
bounds, secret flags, placeholders, visibility). Fields intentionally not
rendered must be listed in DASHBOARD_HIDDEN_FIELDS with a reason — enforced by
the parity gate (plan 08).

Bind note: the runtime bind (``bind_host`` / ``port_range_*`` / ``auto_port``) is
a first-class ``config.yaml`` ``bind:`` section backed by ``BindConfig``. It
auto-renders here like any other registry section. ``server:`` retains only
``read_only``; the legacy ``api:`` section and dead ``server.url/host/port/auto_port``
fields are retired.
"""

from __future__ import annotations

from typing import Any

from brainpalace_cli import config_fields as cf
from brainpalace_cli import config_schema as cs
from brainpalace_cli.providers import PROVIDERS

from brainpalace_dashboard import model_introspect as mi

# Section render order + human labels — sourced from the CLI registry (single
# source); a rename in cf.GROUP_ORDER reflects here automatically.
SECTION_ORDER: list[tuple[str, str]] = list(cf.GROUP_ORDER)

# Section intros — sourced from the CLI registry (single source).
SECTION_DESCRIPTIONS: dict[str, str] = dict(cf.GROUP_DESCRIPTIONS)

# All config sections are now model-backed (bind/server via BindConfig/ServerConfig,
# the rest via their pydantic models). The legacy modelless `project` identity card
# was removed — project_root lives in runtime.json + the Instances view, and the
# state-dir location is a BRAINPALACE_STATE_DIR env-only bootstrap knob.
_MODELLESS_SECTION_FIELDS: dict[str, set[str]] = {}


# A rendered section whose CONFIG keys live under a different dotpath namespace.
# `session_archiving` renders as its own section but its keys are the nested
# `session_indexing.archive.*` leaves (single-sourced with the CLI registry, where
# the archive specs are reassigned to the `session_archiving` group).
SECTION_DOTPATH_PREFIX: dict[str, str] = {
    "session_archiving": "session_indexing.archive",
}


def _section_known(section: str) -> set[str]:
    """Field surface for a section — model-derived where a model exists.

    Model-backed sections reflect ``<Model>.model_fields`` (the single source of
    truth), so a field added to the model auto-surfaces. The model-less runtime/
    identity sections fall back to config_schema.
    """
    if section == "session_archiving":
        return set(SESSION_ARCHIVE_FIELDS)
    if section in mi.SECTION_MODELS:
        return mi.model_field_names(section)
    return _MODELLESS_SECTION_FIELDS.get(section, set())


# Field order within a section is single-sourced from cf.SECTION_FIELD_ORDER
# (baked into FieldSpec.order); see _ordered_fields.

# Enum options that the model annotation CANNOT express — these fields are plain
# `str` validated by a field_validator (not Literal/Enum), so the choices live in
# config_schema. Every OTHER enum (providers, bm25.engine, extraction.mode, etc.)
# derives its options straight from the model annotation via model_introspect.
ENUM_FALLBACKS: dict[str, list[str]] = {
    "storage.backend": sorted(cs.VALID_STORAGE_BACKENDS),
    "graphrag.store_type": sorted(cs.VALID_GRAPHRAG_STORE_TYPES),
}

# Effective defaults the model itself cannot give: graphrag.* default to None in
# the model (an absent YAML key defers to the env/Settings layer), so the
# *effective* defaults are mirrored here from settings.py (GRAPH_*). Every other
# section's defaults derive from the model.
# Single-sourced from the CLI registry so the dashboard and the `init` review grid
# resolve the same effective default for settings-fallback fields (graphrag.*,
# compute.min_confidence). Do NOT redefine here — edit cf.DEFAULT_FALLBACKS.
DEFAULT_FALLBACKS: dict[str, Any] = cf.DEFAULT_FALLBACKS


def _model_presets(kind: str) -> list[str]:
    """Union of all models across a kind's providers (recommended-first per
    provider), de-duplicated. The frontend narrows this to the selected
    provider's models; this static union is the no-JS fallback."""
    seen: dict[str, None] = {}
    for prov in PROVIDERS[kind].values():
        for m in prov["models"]:
            seen.setdefault(m, None)
    return list(seen)


# Presentation overrides for the values the registry does NOT own: secret flags,
# model presets, placeholders, numeric bounds, and visible_when conditions.
# LABELS and HELP are sourced from the CLI field registry
# (brainpalace_cli.config_fields) — the single source — and were migrated out of
# here verbatim; do not re-add label/help for a model-backed field. (Non-model
# fields like storage.postgres.* still keep their label/help here.)
OVERRIDES: dict[str, dict[str, Any]] = {
    "embedding.api_key": {"secret": True},
    "summarization.api_key": {"secret": True},
    "storage.postgres.password": {"secret": True},
    "embedding.api_key_env": {"placeholder": "OPENAI_API_KEY"},
    "summarization.api_key_env": {"placeholder": "ANTHROPIC_API_KEY"},
    "embedding.model": {"presets": _model_presets("embedding")},
    "summarization.model": {"presets": _model_presets("summarization")},
    "reranker.model": {"presets": _model_presets("reranker")},
    "git_indexing.depth": {"min": 0},
    "git_indexing.max_files": {"min": 0},
    "extraction.grace_hours": {"min": 0},
    "extraction.drain_batch_size": {"min": 1},
    "extraction.drain_cooldown_seconds": {"min": 0},
    "query_log.retention_days": {"min": 0, "max": 365},
    "session_indexing.archive.retain_days": {"min": 0},
    "session_indexing.archive.reconcile_seconds": {"min": 1},
}


def _visible_when(dotpath: str) -> dict[str, str] | None:
    """Dashboard ``visible_when`` derived from the CLI single source
    (``cf.FIELD_VISIBLE_WHEN``) so the two surfaces never drift."""
    cond = cf.FIELD_VISIBLE_WHEN.get(dotpath)
    return {"field": cond[0], "equals": cond[1]} if cond else None


# Fields deliberately not shown in the form (parity gate requires a reason).
# Dashboard-only hides + the CLI grid-hidden set (cf.GRID_HIDDEN_FIELDS) merged in
# below, so a field the CLI review grid suppresses is hidden here too (parity).
_DASHBOARD_ONLY_HIDDEN: dict[str, str] = {
    # GraphRAGConfig models several internal knobs that are not part of the
    # user-facing surface (tuning internals, persistence paths set by the server).
    # The user-facing graphrag controls (enabled / store_type / use_code_metadata)
    # render; doc-graph extraction is now configured via extraction.mode.
    # The rest are hidden here with a reason so a genuinely NEW graphrag field
    # still auto-surfaces.
    "graphrag.index_path": "server-managed persistence path; not user-tunable",
    "graphrag.extraction_model": "internal extraction model; set via providers/env",
    "graphrag.max_triplets_per_chunk": "advanced extraction-tuning internal",
    "graphrag.traversal_depth": "advanced query-tuning internal",
    "graphrag.rrf_k": "advanced multi-retrieval fusion constant (internal)",
}

# Grid-hidden fields (from the CLI single source, cf.GRID_HIDDEN_FIELDS) are merged
# in below. GRID_HIDDEN_FIELDS is currently empty; the merge is retained for future use.
DASHBOARD_HIDDEN_FIELDS: dict[str, str] = {
    **_DASHBOARD_ONLY_HIDDEN,
    **cf.GRID_HIDDEN_FIELDS,
}

# Fields shown but NOT editable. (Currently none — the legacy project identity
# paths were removed; project_root lives in runtime.json + the Instances view.)
DASHBOARD_READONLY_FIELDS: dict[str, str] = {}

# Sub-fields of session_indexing.archive (modeled by server SessionArchiveConfig:
# enabled / dir / retain_days / reconcile_seconds). Rendered as a nested group.
SESSION_ARCHIVE_FIELDS: list[str] = [
    "enabled",
    "dir",
    "retain_days",
    "reconcile_seconds",
]

# Sentinel: this field has no derivable default (distinct from a real `None`
# default, which IS surfaced as "none").
_NO_DEFAULT = object()


def _derive(section: str, key: str) -> dict[str, Any]:
    """Widget + default + enum options for a field, from the model where possible.

    Dispatches on the field's location:
    - a section backed by a pydantic model -> reflect the model;
    - the nested archive model -> reflect SessionArchiveConfig;
    - ``storage.postgres.*`` (a raw dict, no model) -> config_schema type hints;
    - model-less api/server/project -> plain text, no default.
    Then layer the small fallbacks the model can't express (ENUM_FALLBACKS,
    DEFAULT_FALLBACKS).
    """
    prefix = SECTION_DOTPATH_PREFIX.get(section, section)
    dotpath = f"{prefix}.{key}"
    derived: dict[str, Any]
    if prefix in mi.SECTION_MODELS:
        derived = mi.derive_field(prefix, key)
    elif prefix == "session_indexing.archive":
        derived = mi.nested_field("session_indexing.archive", key)
    elif prefix == "storage.postgres":
        t = dict(cs.POSTGRES_TYPE_FIELDS).get(key, (str, ""))[0]
        widget = "int" if t is int else "toggle" if t is bool else "text"
        derived = {"widget": widget, "default": _NO_DEFAULT}
    else:  # model-less runtime/identity sections (api/server/project)
        derived = {"widget": "text", "default": _NO_DEFAULT}

    # Enum options: prefer the model-derived options; fall back to config_schema
    # for the plain-str-validated fields whose annotation can't enumerate them.
    if dotpath in ENUM_FALLBACKS:
        derived["widget"] = "enum"
        derived["options"] = ENUM_FALLBACKS[dotpath]
    elif "options" in derived:
        derived["options"] = sorted(derived["options"])

    # Effective default: model value, overridden by the settings-sourced fallback
    # (graphrag.*), which also forces it onto the surfaced graphrag controls.
    if dotpath in DEFAULT_FALLBACKS:
        derived["default"] = DEFAULT_FALLBACKS[dotpath]
    return derived


def _field(section: str, key: str) -> dict[str, Any]:
    prefix = SECTION_DOTPATH_PREFIX.get(section, section)
    dotpath = f"{prefix}.{key}"
    ov = OVERRIDES.get(dotpath, {})
    spec = cf.FIELD_SPECS.get(dotpath)
    derived = _derive(section, key)
    # Label sourced from the registry (spec.prompt) — equals the prior OVERRIDES
    # label where present, else the auto-capitalized key. Non-model fields
    # (storage.postgres.*, modelless api/server/project) have no spec and keep
    # the OVERRIDES/auto label.
    label = spec.prompt if spec else ov.get("label", key.replace("_", " ").capitalize())
    field: dict[str, Any] = {
        "key": key,
        "dotpath": dotpath,
        "label": label,
        "widget": derived["widget"],
        "secret": bool(ov.get("secret", False)),
    }
    if dotpath in DASHBOARD_READONLY_FIELDS:
        field["readonly"] = True
    if field["widget"] == "enum":
        field["options"] = derived["options"]
    if derived.get("default", _NO_DEFAULT) is not _NO_DEFAULT:
        field["default"] = derived["default"]
    # Help sourced from the registry: its FIELD_OVERRIDES carries the verbatim
    # presentation help. Emitted only for fields that HAVE a presentation help
    # override — a field's bare model-description default is not rendered here
    # (matches pre-registry behavior). Non-model fields keep any OVERRIDES help.
    if spec and "help" in cf.FIELD_OVERRIDES.get(dotpath, {}) and spec.help:
        field["help"] = spec.help
    elif spec is None and "help" in ov:
        field["help"] = ov["help"]
    for opt_key in ("presets", "placeholder", "min", "max", "step", "visible_when"):
        if opt_key in ov:
            field[opt_key] = ov[opt_key]
    vw = _visible_when(dotpath)
    if vw is not None:
        field["visible_when"] = vw
    return field


def _ordered_fields(section: str, known: set[str]) -> list[str]:
    """Section field order — SINGLE-SOURCED from the CLI registry's baked
    ``FieldSpec.order`` (preferred-first then alpha; see cf.SECTION_FIELD_ORDER),
    so the dashboard and the init grid order fields identically. Modelless fields
    with no spec fall back to alphabetical."""
    prefix = SECTION_DOTPATH_PREFIX.get(section, section)

    def rank(f: str) -> tuple[int, str]:
        spec = cf.FIELD_SPECS.get(f"{prefix}.{f}")
        return (spec.order if spec else 999, f)

    return sorted(known, key=rank)


def build_ui_schema() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for key, label in SECTION_ORDER:
        prefix = SECTION_DOTPATH_PREFIX.get(key, key)
        known = _ordered_fields(key, _section_known(key))
        fields: list[dict[str, Any]] = []
        for fld in known:
            dotpath = f"{prefix}.{fld}"
            if dotpath in DASHBOARD_HIDDEN_FIELDS:
                continue
            # Nested objects are expanded as groups below, not flat controls.
            if dotpath in ("storage.postgres", "session_indexing.archive"):
                continue
            fields.append(_field(key, fld))
        if key == "storage":
            fields.append(
                {
                    "key": "postgres",
                    "dotpath": "storage.postgres",
                    "label": "PostgreSQL",
                    "widget": "group",
                    "visible_when": _visible_when("storage.postgres"),
                    "fields": [
                        _field("storage.postgres", k)
                        for k in sorted(cs.POSTGRES_KNOWN_FIELDS)
                    ],
                }
            )
        # Skip sections whose every field is hidden (e.g. api/server/project are
        # runtime-managed and fully hidden) — don't render an empty header.
        if not fields:
            continue
        section_obj: dict[str, Any] = {"key": key, "label": label, "fields": fields}
        if key in SECTION_DESCRIPTIONS:
            section_obj["description"] = SECTION_DESCRIPTIONS[key]
        sections.append(section_obj)
    # `providers` is the canonical provider descriptor (kind -> provider ->
    # {models, needs_base_url, default_api_key_env}). The frontend uses it to
    # reshape the embedding/summarization/reranker sections when the selected
    # provider changes (model presets, base_url visibility, api_key_env hint).
    return {"sections": sections, "providers": _providers_payload()}


def _providers_payload() -> dict[str, Any]:
    """JSON-safe copy of the provider descriptor for GET /schema."""
    return {
        kind: {prov: dict(info) for prov, info in provs.items()}
        for kind, provs in PROVIDERS.items()
    }


def effective_defaults() -> dict[str, Any]:
    """``dotpath -> effective code default`` for every rendered field that has
    one. Derived from the SAME schema the form renders, so it auto-tracks the
    models (no hand-maintained default table). Consumed by config_svc to label a
    key's source as ``default`` when neither project nor global sets it."""
    out: dict[str, Any] = {}
    for sec in build_ui_schema()["sections"]:
        for fld in sec["fields"]:
            if fld.get("widget") == "group":
                for child in fld.get("fields", []):
                    if "default" in child:
                        out[child["dotpath"]] = child["default"]
            elif "default" in fld:
                out[fld["dotpath"]] = fld["default"]
    return out


#: Back-compat module constant (was a hand-authored table; now model-derived).
DEFAULTS: dict[str, Any] = effective_defaults()
