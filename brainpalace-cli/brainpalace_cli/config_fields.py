"""Single source of truth for config FIELD PRESENTATION (group, order, prompt,
help, widget, enum-options source, init role). Consumed by the dashboard
ui_schema (order/help/label) and by the CLI prompt renderer + review screen.

Field TYPES/DEFAULTS live in the server pydantic models; ENUM VALUES live in the
model annotations / providers.PROVIDERS / config_schema.VALID_*. This registry
references them — it never copies the lists, and it never imports the dashboard.
"""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass, replace
from typing import Any, Literal, Union, get_args, get_origin

from brainpalace_server.config.bind_config import BindConfig
from brainpalace_server.config.bm25_config import BM25Config
from brainpalace_server.config.extraction_config import ExtractionConfig
from brainpalace_server.config.git_config import GitIndexingConfig
from brainpalace_server.config.indexing_config import IndexingConfig
from brainpalace_server.config.provider_config import (
    ComputeConfig,
    EmbeddingConfig,
    GraphRAGConfig,
    RerankerConfig,
    StorageConfig,
    SummarizationConfig,
    load_merged_config_dict,
)
from brainpalace_server.config.query_log_config import QueryLogConfig
from brainpalace_server.config.server_config import ServerConfig
from brainpalace_server.config.session_config import (
    SessionArchiveConfig,
    SessionExtractionConfig,
    SessionIndexingConfig,
)
from brainpalace_server.config.usage_metrics_config import UsageMetricsConfig
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from brainpalace_cli import config_schema as cs
from brainpalace_cli.providers import PROVIDERS


@dataclass(frozen=True)
class FieldSpec:
    dotpath: str
    group: str
    order: int
    prompt: str
    help: str
    widget: str  # text | bool | choice | int | float
    options_ref: str | None = None
    init_role: str = "normal"  # normal | advanced | consent | hidden
    secret: bool = False
    scope: str = "both"  # global | project | both


# Canonical section -> model (moved here from the dashboard; re-exported there).
SECTION_MODELS: dict[str, type[BaseModel]] = {
    "embedding": EmbeddingConfig,
    "summarization": SummarizationConfig,
    "reranker": RerankerConfig,
    "storage": StorageConfig,
    "graphrag": GraphRAGConfig,
    "query_log": QueryLogConfig,
    "bm25": BM25Config,
    "indexing": IndexingConfig,
    "git_indexing": GitIndexingConfig,
    "session_indexing": SessionIndexingConfig,
    "session_extraction": SessionExtractionConfig,
    "compute": ComputeConfig,
    "extraction": ExtractionConfig,
    "usage_metrics": UsageMetricsConfig,
    "bind": BindConfig,
    "server": ServerConfig,
}
NESTED_MODELS: dict[str, type[BaseModel]] = {
    "session_indexing.archive": SessionArchiveConfig,
}

# Verbatim copy of ui_schema.SECTION_ORDER (16 entries). The dashboard-side test
# (Task 2) asserts cf.GROUP_ORDER == ui_schema.SECTION_ORDER.
GROUP_ORDER: list[tuple[str, str]] = [
    ("embedding", "Embedding"),
    ("summarization", "Summarization"),
    ("reranker", "Reranker"),
    ("bm25", "BM25"),
    ("graphrag", "GraphRAG"),
    ("compute", "Compute Query"),
    ("storage", "Storage"),
    ("indexing", "Indexing"),
    ("git_indexing", "Git Indexing"),
    # `session_archiving` is the free raw-transcript COPY. Its config keys live
    # under the nested `session_indexing.archive.*` namespace, but it renders as
    # its OWN section (before the billable embed) on BOTH the dashboard and the
    # init grid — the archive specs are reassigned to this group in build_specs().
    ("session_archiving", "Chat Session : Archiving"),
    ("session_indexing", "Chat Session : Vector Indexing"),
    ("session_extraction", "Chat Session : Summarization"),
    ("extraction", "Extraction Engine"),
    ("bind", "Server"),
    ("server", "Server Mode"),
    ("query_log", "Query Log"),
    ("usage_metrics", "Usage Metrics"),
]

# Section "what this does" intros. Single source — the dashboard's
# ui_schema.SECTION_DESCRIPTIONS derives from this; the CLI review grid renders
# it as each division's intro. Keys match the dashboard section keys (incl. the
# `session_archiving` pseudo-section the dashboard splits from session_indexing).
GROUP_DESCRIPTIONS: dict[str, str] = {
    "server": "Server-level switches. read_only turns the server query-only: "
    "no embedding, summarization, or index writes.",
    "bind": "Runtime bind settings — host/IP and port range the server uses at "
    "start. Inherited project→global like every other config.yaml key. "
    "Changes take effect on the next server restart.",
    "storage": "Where indexed vectors live. chroma is the zero-setup local "
    "default; postgres is for shared/larger deployments.",
    "graphrag": "The knowledge graph (entities + relationships) that powers "
    "graph and multi query modes.",
    "git_indexing": "Index git history so past commits and decisions are "
    "searchable alongside code.",
    "session_archiving": "COPIES raw chat transcripts verbatim to a local folder "
    "— a free, durable backup. Does NOT embed or summarize; just the raw store.",
    "session_indexing": "EMBEDS raw chat transcripts into vectors for semantic "
    "recall (billable). Separate from the copy (Chat Session : Archiving) and the "
    "summary (Chat Session : Summarization).",
    "session_extraction": "DISTILLS a finished chat transcript into a structured "
    "summary, decisions, and graph triples — the curated 'memory'. Not a copy "
    "(Chat Session : Archiving) and not an embed (Chat Session : Vector Indexing).",
    "compute": "Aggregation query mode that sums typed numeric records extracted "
    "from sessions. Powers the compute query mode.",
    "extraction": "Shared LLM extraction engine — selects how doc-graph triplets "
    "AND session distillation are processed. Default off (cost-safe). "
    "subagent = free Claude Code Haiku; provider = server-side LLM (BILLABLE, "
    "requires EXTRACTION_PROVIDER_ENABLED=true); auto = subagent + paid safety-net.",
    "indexing": "Large-file re-embed guards and which paths are skipped when "
    "indexing. exclude_patterns are globs never indexed.",
}


def _unwrap_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def _auto_widget(annotation: Any) -> str:
    ann = _unwrap_optional(annotation)
    origin = get_origin(ann)
    if origin is Literal:
        return "choice"
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return "choice"
    if ann is bool:
        return "bool"
    if ann is int:
        return "int"
    if ann is float:
        return "float"
    return "text"


def _annotation_options(annotation: Any) -> list[str] | None:
    ann = _unwrap_optional(annotation)
    if get_origin(ann) is Literal:
        return [str(a) for a in get_args(ann)]
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return [str(m.value) for m in ann]
    return None


# Validator-only enums (plain str + field_validator) whose options are NOT in
# the annotation — sourced from the public VALID_* sets, never _SECTION_SCHEMA.
_VALIDATOR_ENUMS: dict[str, set[str]] = {
    "storage.backend": cs.VALID_STORAGE_BACKENDS,
    "graphrag.store_type": cs.VALID_GRAPHRAG_STORE_TYPES,
}


def options_for(ref: str) -> list[str]:
    kind, _, arg = ref.partition(":")
    if kind == "providers":
        return list(PROVIDERS[arg].keys())
    if kind == "models":
        seen: dict[str, None] = {}
        for prov in PROVIDERS[arg].values():
            for m in prov["models"]:
                seen.setdefault(m, None)
        return list(seen)
    if kind == "validator":
        return sorted(_VALIDATOR_ENUMS[arg])
    if kind == "annotation":
        section, _, field = arg.partition(".")
        ann = SECTION_MODELS[section].model_fields[field].annotation
        return _annotation_options(ann) or []
    raise KeyError(f"unknown options_ref: {ref}")


def _auto_options_ref(section: str, field: str, annotation: Any) -> str | None:
    if field == "provider":
        return f"providers:{section}"
    if field == "model":
        return f"models:{section}"
    dp = f"{section}.{field}"
    if dp in _VALIDATOR_ENUMS:
        return f"validator:{dp}"
    if _annotation_options(annotation) is not None:
        return f"annotation:{dp}"
    return None


# --- Verbatim help/label strings migrated out of ui_schema.OVERRIDES ----------
# These must stay byte-identical so Milestone A's golden snapshot does not move.
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

# OPTIONAL per-dotpath overlay. Carries the verbatim help + label migrated out of
# ui_schema.OVERRIDES (so the dashboard stays byte-identical) PLUS the init_role
# curation. Only FieldSpec keys are permitted here (prompt/help/order/widget/
# options_ref/group/init_role/secret) — presentation-only dashboard keys
# (presets/placeholder/min/max/visible_when) stay in ui_schema.OVERRIDES.
FIELD_OVERRIDES: dict[str, dict[str, Any]] = {
    # --- embedding ---
    "embedding.provider": {
        "help": "Embedding provider. Drives the model choices, base URL, and "
        "expected API-key env var below.",
    },
    "embedding.model": {
        "help": "Embedding model. Presets follow the selected provider; pick "
        "Custom… for any other model.",
    },
    "embedding.base_url": {"help": _BASE_URL_HELP},
    "embedding.api_key_env": {
        "prompt": "API key env var",
        "help": _API_KEY_ENV_HELP,
        "init_role": "advanced",
    },
    "embedding.api_key": {
        "prompt": "API key (inline — prefer env var)",
        "help": _API_KEY_HELP,
        "init_role": "hidden",
        "secret": True,
    },
    "embedding.params": {
        "help": "Extra provider params (key/value). Passed through to the client.",
        "init_role": "hidden",
    },
    # --- summarization ---
    "summarization.provider": {
        "help": "Summarization provider used for chat-session distillation and "
        "doc-graph triplet extraction (extraction.mode=provider/auto). Drives "
        "the model choices, base URL, and expected API-key env var below.",
    },
    "summarization.model": {
        "help": "Summarization model. Presets follow the selected provider; pick "
        "Custom… for any other model.",
    },
    "summarization.base_url": {"help": _BASE_URL_HELP},
    "summarization.api_key_env": {
        "prompt": "API key env var",
        "help": _API_KEY_ENV_HELP,
        "init_role": "advanced",
    },
    "summarization.api_key": {
        "prompt": "API key (inline — prefer env var)",
        "help": _API_KEY_HELP,
        "init_role": "hidden",
        "secret": True,
    },
    "summarization.params": {
        "help": "Extra provider params (key/value). Passed through to the client.",
        "init_role": "hidden",
    },
    # --- reranker ---
    "reranker.enabled": {
        "prompt": "Enabled",
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
        "help": "sentence-transformers: a cross-encoder model (empty = built-in "
        "default cross-encoder/ms-marco-MiniLM-L-6-v2). ollama: any chat model "
        "(e.g. llama3.2:1b) used for prompt-based relevance scoring.",
    },
    "reranker.base_url": {"help": _BASE_URL_HELP},
    "reranker.params": {
        "help": "Extra reranker params (key/value). Passed through to the client.",
        "init_role": "hidden",
    },
    # --- storage ---
    "storage.backend": {
        "help": "chroma = local on-disk vector DB, single process, zero setup "
        "(default). postgres = shared/multi-client store for larger or "
        "multi-user deployments; requires a running PostgreSQL and the "
        "PostgreSQL fields below.",
    },
    # --- graphrag ---
    "graphrag.enabled": {
        "prompt": "Enabled",
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
    "graphrag.use_code_metadata": {
        "prompt": "Use code metadata",
        "help": "Enrich graph nodes with code-structure metadata (symbols, "
        "signatures) for richer graph queries. Default: on.",
    },
    "graphrag.index_path": {"init_role": "hidden"},
    "graphrag.extraction_model": {"init_role": "hidden"},
    "graphrag.max_triplets_per_chunk": {"init_role": "advanced"},
    "graphrag.traversal_depth": {"init_role": "advanced"},
    "graphrag.rrf_k": {"init_role": "advanced"},
    # --- server ---
    "server.read_only": {"prompt": "Read Only Mode"},
    # --- query_log ---
    "query_log.enabled": {"prompt": "Enable query history"},
    "query_log.retention_days": {
        "prompt": "Retention (days)",
        "help": "0 = keep forever",
    },
    # --- bm25 ---
    "bm25.detect": {
        "prompt": "Auto-detect language (per document)",
        "help": "Detect each document's language individually (py3langid). When "
        "off, every document uses the default language below. Default: off.",
    },
    "bm25.language": {
        "prompt": "Default / fallback language",
        "help": "Tokenizer language used as the default, and the fallback when "
        "auto-detect is off or below the confidence threshold. Default: en.",
    },
    "bm25.detect_min_confidence": {
        "prompt": "Auto-detect min confidence",
        "help": "Below this confidence, a document falls back to the default "
        "language. Only used when auto-detect is on. Default: 0.6.",
    },
    # --- git_indexing ---
    "git_indexing.enabled": {
        "prompt": "Enabled",
        "help": "Index git history (commit messages + changed paths) so past "
        "decisions are searchable. Default: off.",
        "init_role": "consent",
    },
    "git_indexing.depth": {
        "prompt": "History depth (commits)",
        "help": "How many commits back to index. 0 = full history. Default: 0.",
    },
    "git_indexing.max_files": {
        "prompt": "Max files per commit",
        "help": "Skip commits touching more than this many files (cuts noise from "
        "bulk/vendor commits). Default: 50.",
    },
    "git_indexing.path_filter": {
        "help": "Path globs to include when indexing git history (one per row).",
    },
    # --- session_indexing (vector) ---
    "session_indexing.enabled": {
        "init_role": "consent",
        "prompt": "Vector indexing enabled",
    },
    "session_indexing.include_user_turns": {"init_role": "consent"},
    "session_indexing.retain_days": {"init_role": "advanced"},
    "session_indexing.window": {"init_role": "advanced"},
    "session_indexing.stride": {"init_role": "advanced"},
    "session_indexing.watch_debounce_ms": {"init_role": "advanced"},
    "session_indexing.sessions_dir": {
        "prompt": "Transcript source dir (override)",
        "help": "Where to read AI chat transcripts from. Empty = auto "
        "(~/.claude/projects/...). This is the SOURCE, not the archive "
        "directory (see Session archive below).",
    },
    # --- session_indexing.archive (nested) ---
    "session_indexing.archive.enabled": {"prompt": "Archive enabled"},
    "session_indexing.archive.dir": {
        "prompt": "Archive directory",
        "help": "Where raw transcripts are copied (relative to project or absolute).",
        "scope": "project",
    },
    "session_indexing.archive.retain_days": {
        "prompt": "Retain (days)",
        "help": "0 = keep forever.",
    },
    "session_indexing.archive.reconcile_seconds": {
        "prompt": "Reconcile interval (s)",
        "help": "How often the archive copy/index sweep runs.",
    },
    # --- extraction (shared engine) ---
    "extraction.mode": {
        "help": "LLM engine for BOTH doc-graph triplet extraction and session "
        "distillation. off = code-AST graph only, no prose triplets (default, "
        "cost-safe). subagent = free Claude Code Haiku plugin. "
        "auto = subagent + paid provider safety-net after grace_hours. "
        "provider = server-side LLM only (deterministic, headless-safe, BILLABLE). "
        "Paid paths (auto/provider) also require EXTRACTION_PROVIDER_ENABLED=true.",
        "init_role": "consent",
    },
    "extraction.grace_hours": {
        "prompt": "Grace period (hours)",
        "help": "auto mode only: hours the free subagent gets before the paid "
        "provider drains a doc chunk. 0 = provider drains immediately. Default: 24.",
        "init_role": "advanced",
    },
    "extraction.drain_batch_size": {
        "prompt": "Drain batch size",
        "help": "Max items drained per reconcile tick (shared throttle for both "
        "doc-graph and session extraction). Default: 8.",
        "init_role": "advanced",
    },
    "extraction.drain_cooldown_seconds": {
        "prompt": "Drain cooldown (s)",
        "help": "Minimum seconds between drain ticks (shared cooldown). "
        "Default: 300.",
        "init_role": "advanced",
    },
    "extraction.drain_doc_max_per_turn": {"init_role": "advanced"},
    "extraction.drain_session_max_per_turn": {"init_role": "advanced"},
    "extraction.max_provider_items_per_hour": {"init_role": "advanced"},
    "extraction.provider_session_max_chunks": {"init_role": "advanced"},
    "extraction.provider_context_tokens": {"init_role": "advanced"},
    "extraction.distill_chunk_chars": {"init_role": "advanced"},
    "extraction.max_pending": {"init_role": "advanced"},
    # --- indexing ---
    "indexing.exclude_patterns": {
        "prompt": "Exclude patterns",
        "help": "Glob patterns never indexed (one per row).",
    },
    # --- bind ---
    "bind.bind_host": {"prompt": "Bind host"},
    "bind.port_range_start": {"prompt": "Port range start"},
    "bind.port_range_end": {"prompt": "Port range end"},
    "bind.auto_port": {"prompt": "Auto-pick free port"},
}

# dotpath -> reason for fields that MUST be init_role="consent" (hard-checked by
# the gate so a newly-added billable knob can never silently become a plain
# prompt).
KNOWN_CONSENT_FIELDS: dict[str, str] = {
    "session_indexing.enabled": "embedding chat transcripts is billable",
    "session_indexing.include_user_turns": "indexes raw user turns (secrets)",
    "git_indexing.enabled": "commits can contain secrets",
    "extraction.mode": "auto/provider paths are billable",
}


def _specs_for_model(
    section: str, model: type[BaseModel], base_order: int, prefix: str
) -> list[FieldSpec]:
    out: list[FieldSpec] = []
    for i, (fname, finfo) in enumerate(model.model_fields.items()):
        dp = f"{prefix}{fname}"
        # A nested model field: emit a hidden container spec (so model-field
        # coverage holds) AND recurse to emit the leaf specs.
        if dp in NESTED_MODELS:
            out.append(
                FieldSpec(
                    dotpath=dp,
                    group=section,
                    order=base_order + i,
                    prompt=fname.replace("_", " ").capitalize(),
                    help=finfo.description or "",
                    widget="text",
                    init_role="hidden",
                )
            )
            out += _specs_for_model(
                section, NESTED_MODELS[dp], base_order + i, f"{dp}."
            )
            continue
        secret = fname == "api_key"
        out.append(
            FieldSpec(
                dotpath=dp,
                group=section,
                order=base_order + i,
                prompt=fname.replace("_", " ").capitalize(),
                help=finfo.description or "",
                widget=_auto_widget(finfo.annotation),
                options_ref=_auto_options_ref(section, fname, finfo.annotation),
                init_role="hidden" if secret else "normal",
                secret=secret,
            )
        )
    return out


# Canonical field order WITHIN a section — SINGLE SOURCE for both the dashboard
# and the init review grid. Fields listed here lead (in this order); any field not
# listed is appended alphabetically. `provider`/`enabled` lead so the choice that
# drives the rest of the form is on top (issues #2/#5/#6/#11). `session_archiving`
# orders the nested archive sub-fields (keys are the leaf names under
# session_indexing.archive.*).
SECTION_FIELD_ORDER: dict[str, list[str]] = {
    "embedding": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "summarization": ["provider", "model", "base_url", "api_key_env", "api_key"],
    "reranker": ["enabled", "provider", "model", "base_url"],
    "graphrag": [
        "enabled",
        "extraction_model",
        "use_code_metadata",
        "max_triplets_per_chunk",
        "traversal_depth",
        "rrf_k",
        "store_type",
        "index_path",
    ],
    "git_indexing": [
        "enabled",
        "repo_path",
        "path_filter",
        "depth",
        "max_files",
    ],
    "session_archiving": ["enabled", "dir", "retain_days", "reconcile_seconds"],
}


def _canonical_order(group: str, leaf_name: str) -> int:
    """Sort key for a field within its section: preferred-list index first, then
    alphabetical for the rest (mirrors the dashboard's _ordered_fields)."""
    preferred = SECTION_FIELD_ORDER.get(group, [])
    if leaf_name in preferred:
        return preferred.index(leaf_name)
    return len(preferred) + 1  # alpha rank applied as a tiebreak below


def build_specs() -> dict[str, FieldSpec]:
    out: dict[str, FieldSpec] = {}
    for section, model in SECTION_MODELS.items():
        for spec in _specs_for_model(section, model, 0, f"{section}."):
            ov = FIELD_OVERRIDES.get(spec.dotpath, {})
            out[spec.dotpath] = replace(spec, **ov) if ov else spec
    # Reassign the nested archive leaves to their own rendered section. The config
    # dotpaths stay session_indexing.archive.*; only the GROUP (section) changes.
    for dp, spec in list(out.items()):
        if dp.startswith("session_indexing.archive."):
            out[dp] = replace(spec, group="session_archiving")
    # Bake the canonical intra-section order onto spec.order so group_fields()
    # yields identical ordering on both surfaces (preferred-first, then alpha).
    by_group: dict[str, list[str]] = {}
    for dp, spec in out.items():
        by_group.setdefault(spec.group, []).append(dp)
    for group, dps in by_group.items():
        ranked = sorted(
            dps,
            key=lambda d: (_canonical_order(group, d.split(".")[-1]), d.split(".")[-1]),
        )
        for order, dp in enumerate(ranked):
            out[dp] = replace(out[dp], order=order)
    return out


FIELD_SPECS: dict[str, FieldSpec] = build_specs()

# Tree gating for the CLI review grid: a field (or sub-block) shown/edited only
# when a controlling selector field holds a given value. Mirrors the dashboard's
# ui_schema ``visible_when`` conditions — keep the two in sync. Value is compared
# case-insensitively against ``str(effective)`` (enum -> ``.value``).
FIELD_VISIBLE_WHEN: dict[str, tuple[str, str]] = {
    "storage.postgres": ("storage.backend", "postgres"),
    "bm25.detect_min_confidence": ("bm25.detect", "true"),
}

# Fields the interactive review grid (overview + drill) suppresses entirely —
# legacy/superseded knobs a user should not set here. The dashboard hides these
# too (its ui_schema.DASHBOARD_HIDDEN_FIELDS merges this set), keeping the CLI grid
# and the dashboard in parity. Single source: edit here, not in the dashboard.
GRID_HIDDEN_FIELDS: dict[str, str] = {}


def fields_in_order() -> list[FieldSpec]:
    gi = {g: i for i, (g, _l) in enumerate(GROUP_ORDER)}
    return sorted(FIELD_SPECS.values(), key=lambda s: (gi.get(s.group, 99), s.order))


def _scope_ok(scope: str, layer: str | None) -> bool:
    # layer None => no filtering (dashboard + any defaulted caller see everything).
    return layer is None or scope == "both" or scope == layer


def group_fields(group: str, *, layer: str | None = None) -> list[FieldSpec]:
    return sorted(
        (
            s
            for s in FIELD_SPECS.values()
            if s.group == group and _scope_ok(s.scope, layer)
        ),
        key=lambda s: s.order,
    )


def init_fields(roles: tuple[str, ...] = ("normal",)) -> list[FieldSpec]:
    return [s for s in fields_in_order() if s.init_role in roles]


#: Effective code defaults for fields whose pydantic config-model default is
#: ``None`` because the real default lives as a flat field in the server's
#: ``settings.py`` (the "all-None so an absent key leaves the Settings default"
#: pattern, applied by the lifespan override). Introspecting the model yields
#: ``None``, so both surfaces — the ``init`` review grid (:func:`_model_default`)
#: and the dashboard (``ui_schema.DEFAULT_FALLBACKS`` re-exports this) — patch the
#: resolved default from here. SINGLE SOURCE: keep it in the CLI registry only.
DEFAULT_FALLBACKS: dict[str, Any] = {
    "graphrag.enabled": True,
    "graphrag.store_type": "sqlite",
    "graphrag.use_code_metadata": True,
    "compute.min_confidence": 0.7,
}


def _model_default(dotpath: str) -> Any:
    """Code default for a model-backed dotpath, JSON-safe (enum -> .value).

    Returns ``None`` for non-model dotpaths (e.g. ``storage.postgres.*``) and for
    required fields with no default. For the handful of fields whose model default
    is ``None`` but whose real default lives in ``settings.py``, returns the
    effective value from :data:`DEFAULT_FALLBACKS` (parity with the dashboard).
    """
    if dotpath in DEFAULT_FALLBACKS:
        return DEFAULT_FALLBACKS[dotpath]
    parts = dotpath.split(".")
    model: type[BaseModel]
    if dotpath.startswith("session_indexing.archive."):
        model = NESTED_MODELS["session_indexing.archive"]
        name = parts[-1]
    else:
        section_model = SECTION_MODELS.get(parts[0])
        # Only a direct section.field is model-backed (deeper paths have no model).
        if section_model is None or len(parts) != 2:
            return None
        model = section_model
        name = parts[1]
    if name not in model.model_fields:
        return None
    finfo = model.model_fields[name]
    if finfo.default_factory is not None:
        try:
            return finfo.default_factory()  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001 — never break resolution
            return None
    default = finfo.default
    if default is PydanticUndefined:
        return None
    if isinstance(default, enum.Enum):
        return default.value
    return default


def resolve_value(
    dotpath: str, merged: dict[str, Any] | None = None, *, layer: str = "project"
) -> tuple[Any, str]:
    """Effective value + source (``project|global|default``) for a dotpath.

    Walks the ``code < global < project`` merged dict (defaults to
    :func:`load_merged_config_dict`). A merged hit can't cheaply be split into
    project vs global, so any merged hit is reported as ``"global"``; an absent
    key falls back to the model code default (``"default"``).

    ``layer="global"`` and ``merged is None`` reads the XDG global file directly
    (not the merged project+global stack), reporting a hit as ``"global"``.
    """
    if merged is None:
        if layer == "global":
            from brainpalace_cli.config_resolve import global_config_path, read_yaml

            merged = read_yaml(global_config_path())
        else:
            merged = load_merged_config_dict()
    node: Any = merged
    for part in dotpath.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return _model_default(dotpath), "default"
    return node, "global"


def resolve_value_layered(
    dotpath: str, project: dict[str, Any], global_: dict[str, Any]
) -> tuple[Any, str]:
    """Effective value + TRUE source (project|global|default) from the two layers
    read separately (parity with the dashboard's effective()).

    Unlike :func:`resolve_value`, this reads ``project`` and ``global_`` as separate
    dicts so it can accurately distinguish a project-set value from a global-inherited
    one — fixing the bug where any merged hit was labeled ``"global"`` (finding #2).
    """
    from brainpalace_cli.config_resolve import resolve

    val, src = resolve(dotpath, project, global_)
    if src in ("project", "global"):
        return val, src
    return _model_default(dotpath), "default"
