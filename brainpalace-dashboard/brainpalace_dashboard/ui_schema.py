"""Generate a UI form schema from config_schema (single source of truth).

Every known config field renders automatically. The OVERRIDES dict only
improves presentation (labels, presets, bounds, secret flags, visibility).
Fields intentionally not rendered must be listed in DASHBOARD_HIDDEN_FIELDS
with a reason — enforced by the parity gate (plan 08).

Correctness note (verified against brainpalace-cli source):
``read_config(state_dir)`` reads the runtime bind host/port from ``config.json``
(keys ``bind_host`` / ``port_range_*`` / ``auto_port``), NOT from the
``server.*`` / ``api.*`` sections of ``config.yaml``. Those YAML sections are
part of the validated schema but editing them here would be a no-op for the
running server, so they are hidden rather than shipped as dead controls.
"""

from __future__ import annotations

from typing import Any

from brainpalace_cli import config_schema as cs
from brainpalace_cli.providers import PROVIDERS

from brainpalace_dashboard import model_introspect as mi

# Section render order + human labels.
SECTION_ORDER: list[tuple[str, str]] = [
    ("embedding", "Embedding"),
    ("summarization", "Code & Doc Summarization"),
    ("reranker", "Reranker"),
    ("storage", "Storage"),
    ("graphrag", "GraphRAG"),
    ("api", "API"),
    ("server", "Server"),
    ("project", "Project"),
    ("query_log", "Query Log"),
    ("bm25", "BM25"),
    ("git_indexing", "Git Indexing"),
    ("session_indexing", "Session Vector Indexing"),
    ("session_extraction", "Session Summarization"),
    ("compute", "Compute"),
]

# Optional one-line "what this section does" intros, rendered under the header.
SECTION_DESCRIPTIONS: dict[str, str] = {
    "server": "Server-level switches. The bind host/port are NOT here — they live "
    "in config.json (the Runtime bind section). read_only turns the server "
    "query-only: no embedding, summarization, or index writes.",
    "project": "Identity paths for THIS project, set by `brainpalace init` and "
    "shown read-only. Editing them would break instance discovery, so they are "
    "not editable here.",
    "storage": "Where indexed vectors live. chroma is the zero-setup local "
    "default; postgres is for shared/larger deployments.",
    "graphrag": "The knowledge graph (entities + relationships) that powers "
    "graph and multi query modes.",
    "git_indexing": "Index git history so past commits and decisions are "
    "searchable alongside code.",
    "session_archiving": "COPIES raw chat transcripts verbatim to a local folder "
    "— a free, durable backup. Does NOT embed or summarize; just the raw store.",
    "session_indexing": "EMBEDS raw chat transcripts into vectors for semantic "
    "recall (billable). Separate from the copy (Session Archiving) and the "
    "summary (Session Summarization).",
    "session_extraction": "DISTILLS a finished chat transcript into a structured "
    "summary, decisions, and graph triples — the curated 'memory'. Not a copy "
    "(Session Archiving) and not an embed (Session Vector Indexing).",
    "compute": "Aggregation query mode that sums typed numeric records extracted "
    "from sessions. Powers the compute query mode.",
}

# Sections WITHOUT a pydantic model: runtime bind (api/server) and machine
# identity (project). Their fields come from config_schema and are fully
# hidden / read-only (see DASHBOARD_HIDDEN_FIELDS / DASHBOARD_READONLY_FIELDS).
_MODELLESS_SECTION_FIELDS: dict[str, set[str]] = {
    "api": cs.API_KNOWN_FIELDS,
    "server": cs.SERVER_KNOWN_FIELDS,
    "project": cs.PROJECT_KNOWN_FIELDS,
}


def _section_known(section: str) -> set[str]:
    """Field surface for a section — model-derived where a model exists.

    Model-backed sections reflect ``<Model>.model_fields`` (the single source of
    truth), so a field added to the model auto-surfaces. The model-less runtime/
    identity sections fall back to config_schema.
    """
    if section in mi.SECTION_MODELS:
        return mi.model_field_names(section)
    return _MODELLESS_SECTION_FIELDS.get(section, set())


# Explicit field order within a section (fields not listed are appended
# alphabetically). `provider` leads the provider-backed sections so the choice
# that drives the rest of the form is on top (issues #2/#5/#6/#11).
SECTION_FIELD_ORDER: dict[str, list[str]] = {
    "embedding": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "summarization": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "reranker": ["enabled", "provider", "model", "base_url"],
}

# Enum options that the model annotation CANNOT express — these fields are plain
# `str` validated by a field_validator (not Literal/Enum), so the choices live in
# config_schema. Every OTHER enum (providers, bm25.engine, session_extraction.mode)
# derives its options straight from the model annotation via model_introspect.
ENUM_FALLBACKS: dict[str, list[str]] = {
    "storage.backend": sorted(cs.VALID_STORAGE_BACKENDS),
    "graphrag.store_type": sorted(cs.VALID_GRAPHRAG_STORE_TYPES),
    "graphrag.doc_extractor": sorted(cs.VALID_DOC_EXTRACTORS),
}

# Effective defaults the model itself cannot give: graphrag.* default to None in
# the model (an absent YAML key defers to the env/Settings layer), so the
# *effective* defaults are mirrored here from settings.py (GRAPH_*). Every other
# section's defaults derive from the model.
DEFAULT_FALLBACKS: dict[str, Any] = {
    "graphrag.enabled": True,
    "graphrag.store_type": "sqlite",
    "graphrag.use_code_metadata": True,
    "graphrag.doc_extractor": "langextract",
    "compute.enabled": True,
    "compute.record_extraction": True,
    "compute.min_confidence": 0.7,
}

# Provider/api_key/base_url help text — purpose + expected values + default.
# (Issues #3/#4/#8/#10/#11.) Reranker fields too.
_API_KEY_HELP = (
    "Optional. A literal API key stored in config.yaml (discouraged — secrets in "
    "a file). Prefer the 'API key env var' which names an environment variable. "
    "Empty = use the env var."
)
_API_KEY_ENV_HELP = (
    "Name of the environment variable holding the API key (e.g. OPENAI_API_KEY). "
    "Empty = the provider's conventional default env var."
)
_BASE_URL_HELP = (
    "Custom API endpoint (e.g. Ollama http://localhost:11434, or an "
    "OpenAI-compatible proxy). Empty = provider default."
)


def _model_presets(kind: str) -> list[str]:
    """Union of all models across a kind's providers (recommended-first per
    provider), de-duplicated. The frontend narrows this to the selected
    provider's models; this static union is the no-JS fallback."""
    seen: dict[str, None] = {}
    for prov in PROVIDERS[kind].values():
        for m in prov["models"]:
            seen.setdefault(m, None)
    return list(seen)


# Presentation overrides ONLY. Keys are dotpaths.
OVERRIDES: dict[str, dict[str, Any]] = {
    "embedding.provider": {
        "help": "Embedding provider. Drives the model choices, base URL, and "
        "expected API-key env var below.",
    },
    "summarization.provider": {
        "help": "Summarization provider for code/doc summaries. Drives the model "
        "choices, base URL, and expected API-key env var below.",
    },
    "embedding.api_key": {
        "secret": True,
        "label": "API key (inline — prefer env var)",
        "help": _API_KEY_HELP,
    },
    "summarization.api_key": {
        "secret": True,
        "label": "API key (inline — prefer env var)",
        "help": _API_KEY_HELP,
    },
    "storage.postgres.password": {"secret": True},
    "embedding.api_key_env": {
        "label": "API key env var",
        "placeholder": "OPENAI_API_KEY",
        "help": _API_KEY_ENV_HELP,
    },
    "summarization.api_key_env": {
        "label": "API key env var",
        "placeholder": "ANTHROPIC_API_KEY",
        "help": _API_KEY_ENV_HELP,
    },
    "embedding.base_url": {"help": _BASE_URL_HELP},
    "summarization.base_url": {"help": _BASE_URL_HELP},
    "embedding.model": {
        "presets": _model_presets("embedding"),
        "help": "Embedding model. Presets follow the selected provider; pick "
        "Custom… for any other model.",
    },
    "summarization.model": {
        "presets": _model_presets("summarization"),
        "help": "Summarization model. Presets follow the selected provider; pick "
        "Custom… for any other model.",
    },
    "reranker.enabled": {
        "label": "Enabled",
        "help": "Two-stage retrieval: after the first stage (bm25/vector/hybrid) "
        "returns candidates, a local cross-encoder rescores each (query, chunk) "
        "pair and reorders by relevance. No API cost (local model); adds a little "
        "query latency. Default: off.",
    },
    "reranker.provider": {
        "help": "sentence-transformers = local cross-encoder, no API cost, no base "
        "URL (recommended). ollama = prompt-based scoring served by Ollama; "
        "works with any chat model but is slower and needs a base URL.",
    },
    "reranker.model": {
        "presets": _model_presets("reranker"),
        "help": "sentence-transformers: a cross-encoder model (empty = built-in "
        "default cross-encoder/ms-marco-MiniLM-L-6-v2). ollama: any chat model "
        "(e.g. llama3.2:1b) used for prompt-based relevance scoring.",
    },
    "reranker.base_url": {"help": _BASE_URL_HELP},
    "storage.backend": {
        "help": "chroma = local on-disk vector DB, single process, zero setup "
        "(default). postgres = shared/multi-client store for larger or "
        "multi-user deployments; requires a running PostgreSQL and the "
        "PostgreSQL fields below.",
    },
    "graphrag.enabled": {
        "label": "Enabled",
        "help": "Master switch for the knowledge graph (entities + relationships "
        "mined from code and docs). Powers graph/multi query modes.",
    },
    "graphrag.store_type": {
        "help": "simple = in-memory graph, rebuilt on every server start, with NO "
        "temporal (versioned-over-time) edges — lightest, ephemeral. "
        "sqlite = persistent on-disk graph that supports the temporal "
        "knowledge graph (edges versioned over time). Default and recommended: "
        "sqlite.",
    },
    "graphrag.doc_extractor": {
        "help": "langextract = also mine graph entities/relationships from docs. "
        "none = code graph only (skip doc extraction).",
    },
    "graphrag.use_code_metadata": {
        "label": "Use code metadata",
        "help": "Enrich graph nodes with code-structure metadata (symbols, "
        "signatures) for richer graph queries. Default: on.",
    },
    "git_indexing.enabled": {
        "label": "Enabled",
        "help": "Index git history (commit messages + changed paths) so past "
        "decisions are searchable. Default: off.",
    },
    "git_indexing.depth": {
        "label": "History depth (commits)",
        "min": 0,
        "help": "How many commits back to index. 0 = full history. Default: 0.",
    },
    "git_indexing.max_files": {
        "label": "Max files per commit",
        "min": 0,
        "help": "Skip commits touching more than this many files (cuts noise from "
        "bulk/vendor commits). Default: 50.",
    },
    "session_extraction.mode": {
        "help": "Which engine distills a finished chat into a summary + decisions. "
        "subagent = a Claude Code plugin subagent does it locally (free; "
        "default). provider = the configured summarization provider (a cloud "
        "LLM — may be METERED/paid). auto = pick automatically, with a 24h "
        "safety net that can fire the paid provider path. off = disabled.",
    },
    "query_log.enabled": {"label": "Enable query history"},
    "query_log.retention_days": {
        "label": "Retention (days)",
        "min": 0,
        "max": 365,
        "help": "0 = keep forever",
    },
    # postgres section is only meaningful when storage.backend == postgres
    "storage.postgres": {
        "visible_when": {"field": "storage.backend", "equals": "postgres"}
    },
    "embedding.params": {
        "help": "Extra provider params (key/value). Passed through to the client.",
    },
    "summarization.params": {
        "help": "Extra provider params (key/value). Passed through to the client.",
    },
    "reranker.params": {
        "help": "Extra reranker params (key/value). Passed through to the client.",
    },
    "git_indexing.path_filter": {
        "help": "Path globs to include when indexing git history (one per row).",
    },
    "session_indexing.archive.dir": {
        "label": "Archive directory",
        "help": "Where raw transcripts are copied (relative to project or absolute).",
    },
    "session_indexing.archive.retain_days": {
        "label": "Retain (days)",
        "min": 0,
        "help": "0 = keep forever.",
    },
    "session_indexing.archive.reconcile_seconds": {
        "label": "Reconcile interval (s)",
        "min": 1,
        "help": "How often the archive copy/index sweep runs.",
    },
    # bm25: detect is per-document language auto-detection, NOT a BM25 on/off.
    # language is the default/fallback used when detection is off or low-confidence
    # — the two are complementary, not mutually exclusive (issue #12, option a).
    "bm25.detect": {
        "label": "Auto-detect language (per document)",
        "help": "Detect each document's language individually (py3langid). When "
        "off, every document uses the default language below. Default: off.",
    },
    "bm25.language": {
        "label": "Default / fallback language",
        "help": "Tokenizer language used as the default, and the fallback when "
        "auto-detect is off or below the confidence threshold. Default: en.",
    },
    "bm25.detect_min_confidence": {
        "label": "Auto-detect min confidence",
        "help": "Below this confidence, a document falls back to the default "
        "language. Only used when auto-detect is on. Default: 0.6.",
        "visible_when": {"field": "bm25.detect", "equals": "true"},
    },
    "session_indexing.sessions_dir": {
        "label": "Transcript source dir (override)",
        "help": "Where to read AI chat transcripts from. Empty = auto "
        "(~/.claude/projects/...). This is the SOURCE, not the archive "
        "directory (see Session archive below).",
    },
}

# Fields deliberately not shown in the form (parity gate requires a reason).
DASHBOARD_HIDDEN_FIELDS: dict[str, str] = {
    # server.* / api.* live in config.yaml's schema but the runtime bind reads
    # config.json (bind_host/port_range/auto_port). Editing them here is a no-op;
    # they are editable via the per-instance Runtime panel (config.json) instead.
    "server.url": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.host": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.port": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.auto_port": (
        "runtime bind comes from config.json, not config.yaml; no-op here"
    ),
    "api.host": "runtime bind comes from config.json, not config.yaml; no-op here",
    "api.port": "runtime bind comes from config.json, not config.yaml; no-op here",
    # GraphRAGConfig models several legacy/internal knobs that are not part of
    # the user-facing surface (tuning internals, a superseded extraction path,
    # and persistence paths set by the server). The four user-facing graphrag
    # controls (enabled / store_type / use_code_metadata / doc_extractor) render;
    # the rest are hidden here with a reason so a genuinely NEW graphrag field
    # still auto-surfaces.
    "graphrag.index_path": "server-managed persistence path; not user-tunable",
    "graphrag.extraction_model": "internal extraction model; set via providers/env",
    "graphrag.max_triplets_per_chunk": "advanced extraction-tuning internal",
    "graphrag.use_llm_extraction": "legacy doc-extraction path; use doc_extractor",
    "graphrag.traversal_depth": "advanced query-tuning internal",
    "graphrag.rrf_k": "advanced multi-retrieval fusion constant (internal)",
    "graphrag.langextract_provider": "internal langextract wiring; follows doc_extractor",  # noqa: E501
    "graphrag.langextract_model": "internal langextract wiring; follows doc_extractor",  # noqa: E501
}

# Fields shown but NOT editable — machine identity set by init. Visible for
# transparency (the completeness rule: nothing persistable is silently absent),
# but editing them would break instance discovery, so the form renders them
# disabled. Parity gate requires a reason (test_readonly_fields_valid_and_not_hidden).
DASHBOARD_READONLY_FIELDS: dict[str, str] = {
    "project.state_dir": "internal path, set by init; editing breaks discovery",
    "project.project_root": "internal path, set by init; editing breaks discovery",
}

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
    dotpath = f"{section}.{key}"
    derived: dict[str, Any]
    if section in mi.SECTION_MODELS:
        derived = mi.derive_field(section, key)
    elif section == "session_indexing.archive":
        derived = mi.nested_field("session_indexing.archive", key)
    elif section == "storage.postgres":
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
    dotpath = f"{section}.{key}"
    ov = OVERRIDES.get(dotpath, {})
    derived = _derive(section, key)
    field: dict[str, Any] = {
        "key": key,
        "dotpath": dotpath,
        "label": ov.get("label", key.replace("_", " ").capitalize()),
        "widget": derived["widget"],
        "secret": bool(ov.get("secret", False)),
    }
    if dotpath in DASHBOARD_READONLY_FIELDS:
        field["readonly"] = True
    if field["widget"] == "enum":
        field["options"] = derived["options"]
    if derived.get("default", _NO_DEFAULT) is not _NO_DEFAULT:
        field["default"] = derived["default"]
    for opt_key in (
        "presets",
        "placeholder",
        "min",
        "max",
        "step",
        "help",
        "visible_when",
    ):
        if opt_key in ov:
            field[opt_key] = ov[opt_key]
    return field


def _ordered_fields(section: str, known: set[str]) -> list[str]:
    """Section field order: explicit leaders first, then the rest alphabetical."""
    preferred = [f for f in SECTION_FIELD_ORDER.get(section, []) if f in known]
    rest = sorted(f for f in known if f not in preferred)
    return preferred + rest


def build_ui_schema() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for key, label in SECTION_ORDER:
        known = _ordered_fields(key, _section_known(key))
        fields: list[dict[str, Any]] = []
        for fld in known:
            dotpath = f"{key}.{fld}"
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
                    "visible_when": {"field": "storage.backend", "equals": "postgres"},
                    "fields": [
                        _field("storage.postgres", k)
                        for k in sorted(cs.POSTGRES_KNOWN_FIELDS)
                    ],
                }
            )
        if key == "session_indexing":
            # Archiving (the raw COPY) is its OWN top-level section, emitted just
            # BEFORE Session Vector Indexing — not a sub-group of it. The config
            # keys stay under `session_indexing.archive.*`; only the dashboard
            # presentation splits copy / embed / summarize into three sections.
            sections.append(
                {
                    "key": "session_archiving",
                    "label": "Session Archiving",
                    "description": SECTION_DESCRIPTIONS["session_archiving"],
                    "fields": [
                        _field("session_indexing.archive", k)
                        for k in SESSION_ARCHIVE_FIELDS
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
