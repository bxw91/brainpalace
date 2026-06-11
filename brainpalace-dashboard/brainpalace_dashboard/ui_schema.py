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

# Optional one-line "what this section does" intros, rendered under the header.
SECTION_DESCRIPTIONS: dict[str, str] = {
    "storage": "Where indexed vectors live. chroma is the zero-setup local "
    "default; postgres is for shared/larger deployments.",
    "graphrag": "The knowledge graph (entities + relationships) that powers "
    "graph and multi query modes.",
    "git_indexing": "Index git history so past commits and decisions are "
    "searchable alongside code.",
    "session_extraction": "DISTILLS a finished chat transcript into a structured "
    "summary, decisions, and graph triples. This is the curated 'memory', "
    "separate from raw transcript indexing below.",
    "session_indexing": "ARCHIVES raw chat transcripts and (optionally) EMBEDS "
    "them for semantic recall. Distinct from Session Extraction: this is the "
    "raw store, not the curated summary.",
}

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

# Explicit field order within a section (fields not listed are appended
# alphabetically). `provider` leads the provider-backed sections so the choice
# that drives the rest of the form is on top (issues #2/#5/#6/#11).
SECTION_FIELD_ORDER: dict[str, list[str]] = {
    "embedding": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "summarization": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "reranker": ["enabled", "provider", "model", "base_url"],
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
        "query latency. Default: on.",
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
    "project.state_dir": "internal path, set by init; editing breaks discovery",
    "project.project_root": "internal path, set by init; editing breaks discovery",
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
}

# Sub-fields of session_indexing.archive (modeled by server SessionArchiveConfig:
# enabled / dir / retain_days / reconcile_seconds). Rendered as a nested group.
SESSION_ARCHIVE_FIELDS: list[str] = [
    "enabled",
    "dir",
    "retain_days",
    "reconcile_seconds",
]

# Free-form provider-params dicts (dict[str, scalar]) — rendered with a
# key/value editor (the "dict" widget) rather than left unreachable.
_DICT_FIELDS = {
    "embedding.params",
    "summarization.params",
    "reranker.params",
}

# String-list fields — rendered with a string-list editor (the "stringlist"
# widget).
_STRINGLIST_FIELDS = {
    "git_indexing.path_filter",
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
    "session_indexing.archive.retain_days",
    "session_indexing.archive.reconcile_seconds",
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
    "session_indexing.archive.enabled",
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
    "session_indexing.archive.enabled": True,
    "session_indexing.archive.dir": ".brainpalace/session_archive",
    "session_indexing.archive.retain_days": 0,
    "session_indexing.archive.reconcile_seconds": 600,
    "session_extraction.mode": "subagent",
    "session_extraction.quiescence_seconds": 1800,
    "query_log.enabled": True,
    "query_log.retention_days": 7,
}


def _widget_for(dotpath: str) -> str:
    if dotpath in ENUM_OPTIONS:
        return "enum"
    if dotpath in _DICT_FIELDS:
        return "dict"
    if dotpath in _STRINGLIST_FIELDS:
        return "stringlist"
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


def _ordered_fields(section: str, known: set[str]) -> list[str]:
    """Section field order: explicit leaders first, then the rest alphabetical."""
    preferred = [f for f in SECTION_FIELD_ORDER.get(section, []) if f in known]
    rest = sorted(f for f in known if f not in preferred)
    return preferred + rest


def build_ui_schema() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for key, label in SECTION_ORDER:
        known = _ordered_fields(key, SECTION_KNOWN[key])
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
            fields.append(
                {
                    "key": "archive",
                    "dotpath": "session_indexing.archive",
                    "label": "Session archive",
                    "widget": "group",
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
