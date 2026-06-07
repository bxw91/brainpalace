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

# Section render order + human labels.
SECTION_ORDER: list[tuple[str, str]] = [
    ("embedding", "Embedding"),
    ("summarization", "Summarization"),
    ("reranker", "Reranker"),
    ("storage", "Storage"),
    ("graphrag", "GraphRAG"),
    ("api", "API"),
    ("server", "Server"),
    ("project", "Project"),
    ("query_log", "Query Log"),
    ("bm25", "BM25"),
    ("git_indexing", "Git Indexing"),
    ("session_indexing", "Session Indexing"),
    ("session_extraction", "Session Extraction"),
]

SECTION_KNOWN: dict[str, set[str]] = {
    "embedding": cs.EMBEDDING_KNOWN_FIELDS,
    "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
    "reranker": cs.RERANKER_KNOWN_FIELDS,
    "storage": cs.STORAGE_KNOWN_FIELDS,
    "graphrag": cs.GRAPHRAG_KNOWN_FIELDS,
    "api": cs.API_KNOWN_FIELDS,
    "server": cs.SERVER_KNOWN_FIELDS,
    "project": cs.PROJECT_KNOWN_FIELDS,
    "query_log": cs.QUERY_LOG_KNOWN_FIELDS,
    "bm25": cs.BM25_KNOWN_FIELDS,
    "git_indexing": cs.GIT_INDEXING_KNOWN_FIELDS,
    "session_indexing": cs.SESSION_INDEXING_KNOWN_FIELDS,
    "session_extraction": cs.SESSION_EXTRACTION_KNOWN_FIELDS,
}

# field dotpath -> enum options (from config_schema enum sets).
ENUM_OPTIONS: dict[str, list[str]] = {
    "embedding.provider": sorted(cs.VALID_EMBEDDING_PROVIDERS),
    "summarization.provider": sorted(cs.VALID_SUMMARIZATION_PROVIDERS),
    "reranker.provider": sorted(cs.VALID_RERANKER_PROVIDERS),
    "storage.backend": sorted(cs.VALID_STORAGE_BACKENDS),
    "graphrag.store_type": sorted(cs.VALID_GRAPHRAG_STORE_TYPES),
    "graphrag.doc_extractor": sorted(cs.VALID_DOC_EXTRACTORS),
    "bm25.engine": sorted(cs.VALID_BM25_ENGINES),
    "session_extraction.mode": sorted(cs.VALID_EXTRACT_MODES),
}

# Presentation overrides ONLY. Keys are dotpaths.
OVERRIDES: dict[str, dict[str, Any]] = {
    "embedding.api_key": {"secret": True, "label": "API key (inline — prefer env var)"},
    "summarization.api_key": {
        "secret": True,
        "label": "API key (inline — prefer env var)",
    },
    "storage.postgres.password": {"secret": True},
    "embedding.api_key_env": {
        "label": "API key env var",
        "placeholder": "OPENAI_API_KEY",
    },
    "summarization.api_key_env": {
        "label": "API key env var",
        "placeholder": "ANTHROPIC_API_KEY",
    },
    "embedding.model": {
        "presets": [
            "text-embedding-3-small",
            "text-embedding-3-large",
            "nomic-embed-text",
        ]
    },
    "summarization.model": {
        "presets": ["claude-3-5-haiku-latest", "claude-sonnet-4-6", "gpt-4o-mini"]
    },
    "graphrag.use_code_metadata": {"label": "Use code metadata"},
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
}

# Fields deliberately not shown in the form (parity gate requires a reason).
DASHBOARD_HIDDEN_FIELDS: dict[str, str] = {
    "project.state_dir": "internal path, set by init; editing breaks discovery",
    "project.project_root": "internal path, set by init; editing breaks discovery",
    # Free-form provider params dicts are not simple click-only controls.
    "embedding.params": "free-form provider params dict; not a simple control",
    "summarization.params": "free-form provider params dict; not a simple control",
    "reranker.params": "free-form provider params dict; not a simple control",
    # server.* / api.* live in config.yaml's schema but the runtime bind reads
    # config.json (bind_host/port_range/auto_port). Editing them here is a no-op.
    "server.url": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.host": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.port": "runtime bind comes from config.json, not config.yaml; no-op here",
    "server.auto_port": (
        "runtime bind comes from config.json, not config.yaml; no-op here"
    ),
    "api.host": "runtime bind comes from config.json, not config.yaml; no-op here",
    "api.port": "runtime bind comes from config.json, not config.yaml; no-op here",
    "git_indexing.path_filter": "list of path globs; not a simple control",
    "session_indexing.archive": "nested session-archive object; not a simple control",
}

# Type hints from config_schema (int/bool). Defaults to text otherwise.
_INT_FIELDS = {
    f"storage.postgres.{k}" for k, (t, _) in cs.POSTGRES_TYPE_FIELDS.items() if t is int
} | {
    "query_log.retention_days",
    "git_indexing.depth",
    "git_indexing.max_files",
    "session_indexing.retain_days",
    "session_indexing.window",
    "session_indexing.stride",
    "session_indexing.watch_debounce_ms",
    "session_extraction.quiescence_seconds",
}
_BOOL_FIELDS = {
    "reranker.enabled",
    "graphrag.enabled",
    "graphrag.use_code_metadata",
    "query_log.enabled",
    "bm25.detect",
    "git_indexing.enabled",
    "session_indexing.enabled",
    "session_indexing.include_user_turns",
} | {
    f"storage.postgres.{k}"
    for k, (t, _) in cs.POSTGRES_TYPE_FIELDS.items()
    if t is bool
}


# Effective default for each field when the project's config.yaml omits it.
# Sourced from the server's pydantic config models / Settings (verified):
# bm25_config.BM25Config, git_config.GitIndexingConfig, session_config.*,
# settings.py (GRAPH_*), and the chroma storage default. Surfaced in the form so
# users see what's active even when a section is unset. `None` = no default value
# (shown as "none").
DEFAULTS: dict[str, Any] = {
    "reranker.enabled": True,
    "storage.backend": "chroma",
    "graphrag.enabled": True,
    "graphrag.store_type": "sqlite",
    "graphrag.doc_extractor": "langextract",
    "graphrag.use_code_metadata": True,
    "bm25.language": "en",
    "bm25.engine": "stem",
    "bm25.detect": False,
    "bm25.detect_min_confidence": 0.6,
    "git_indexing.enabled": False,
    "git_indexing.depth": 0,
    "git_indexing.max_files": 50,
    "session_indexing.enabled": True,
    "session_indexing.include_user_turns": False,
    "session_indexing.retain_days": 0,
    "session_indexing.window": 4,
    "session_indexing.stride": 2,
    "session_indexing.watch_debounce_ms": 30000,
    "session_indexing.sessions_dir": None,
    "session_extraction.mode": "subagent",
    "session_extraction.quiescence_seconds": 1800,
    "query_log.enabled": True,
    "query_log.retention_days": 7,
}


def _widget_for(dotpath: str) -> str:
    if dotpath in ENUM_OPTIONS:
        return "enum"
    if dotpath in _BOOL_FIELDS:
        return "toggle"
    if dotpath in _INT_FIELDS:
        return "int"
    return "text"


def _field(section: str, key: str) -> dict[str, Any]:
    dotpath = f"{section}.{key}"
    ov = OVERRIDES.get(dotpath, {})
    field: dict[str, Any] = {
        "key": key,
        "dotpath": dotpath,
        "label": ov.get("label", key.replace("_", " ").capitalize()),
        "widget": _widget_for(dotpath),
        "secret": bool(ov.get("secret", False)),
    }
    if field["widget"] == "enum":
        field["options"] = ENUM_OPTIONS[dotpath]
    if dotpath in DEFAULTS:
        field["default"] = DEFAULTS[dotpath]
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


def build_ui_schema() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for key, label in SECTION_ORDER:
        known = sorted(SECTION_KNOWN[key])
        fields: list[dict[str, Any]] = []
        for fld in known:
            dotpath = f"{key}.{fld}"
            if dotpath in DASHBOARD_HIDDEN_FIELDS:
                continue
            # "postgres" is a nested object inside storage — expand it below.
            if dotpath == "storage.postgres":
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
        # Skip sections whose every field is hidden (e.g. api/server/project are
        # runtime-managed and fully hidden) — don't render an empty header.
        if not fields:
            continue
        sections.append({"key": key, "label": label, "fields": fields})
    return {"sections": sections}
