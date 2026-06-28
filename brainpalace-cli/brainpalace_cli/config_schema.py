"""Config schema validation engine for BrainPalace YAML config files.

Provides offline validation of config.yaml against the known BrainPalace schema,
reporting errors with field paths, line numbers, and fix suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Valid value sets
# ---------------------------------------------------------------------------

VALID_TOP_LEVEL_KEYS = {
    "embedding",
    "summarization",
    "reranker",
    "storage",
    "graphrag",
    "compute",
    "bind",
    "server",
    "query_log",
    "bm25",
    "git_indexing",
    "session_indexing",
    "session_extraction",
    "extraction",
    "indexing",
    "dashboard",
    "cli",
    "usage_metrics",
}

VALID_EMBEDDING_PROVIDERS = {"openai", "ollama", "cohere"}
VALID_SUMMARIZATION_PROVIDERS = {"anthropic", "openai", "ollama", "gemini", "grok"}
VALID_RERANKER_PROVIDERS = {"sentence-transformers", "ollama"}
VALID_STORAGE_BACKENDS = {"chroma", "postgres"}
VALID_GRAPHRAG_STORE_TYPES = {"simple", "sqlite"}
VALID_BM25_ENGINES = {"stem", "lemma"}
VALID_EXTRACT_MODES = {"auto", "subagent", "provider", "off"}

# Known sub-keys for each section — unknown keys trigger a warning
EMBEDDING_KNOWN_FIELDS = {
    "provider",
    "model",
    "api_key",
    "api_key_env",
    "base_url",
    "params",
}
SUMMARIZATION_KNOWN_FIELDS = {
    "provider",
    "model",
    "api_key",
    "api_key_env",
    "base_url",
    "params",
}
RERANKER_KNOWN_FIELDS = {
    "enabled",
    "provider",
    "model",
    "base_url",
    "params",
}
STORAGE_KNOWN_FIELDS = {"backend", "postgres"}
POSTGRES_KNOWN_FIELDS = {
    "host",
    "port",
    "database",
    "user",
    "password",
    "pool_size",
    "pool_max_overflow",
    "pool_timeout",
    "language",
    "hnsw_m",
    "hnsw_ef_construction",
    "debug",
}
POSTGRES_TYPE_FIELDS: dict[str, tuple[type, str]] = {
    "port": (int, "storage.postgres.port must be an integer"),
    "pool_size": (int, "storage.postgres.pool_size must be an integer"),
    "pool_max_overflow": (int, "storage.postgres.pool_max_overflow must be an integer"),
    "pool_timeout": (int, "storage.postgres.pool_timeout must be an integer"),
    "hnsw_m": (int, "storage.postgres.hnsw_m must be an integer"),
    "hnsw_ef_construction": (
        int,
        "storage.postgres.hnsw_ef_construction must be an integer",
    ),
    "debug": (bool, "storage.postgres.debug must be a boolean (true/false)"),
}
GRAPHRAG_KNOWN_FIELDS = {
    "enabled",
    "store_type",
    "use_code_metadata",
}
# `compute:` section — mirrors brainpalace_server.config.provider_config.ComputeConfig.
COMPUTE_KNOWN_FIELDS = {"min_confidence"}
BIND_KNOWN_FIELDS = {"bind_host", "port_range_start", "port_range_end", "auto_port"}
SERVER_KNOWN_FIELDS = {"read_only"}
QUERY_LOG_KNOWN_FIELDS = {"enabled", "retention_days"}
CLI_KNOWN_FIELDS = {
    "show_ai_hint",
    "subagent_guard",
    "search_guard",
    "session_autostart",
    "await_first_start",
}
# `cli.session_autostart` (bool, default True) — when a Claude Code session starts
# in an indexed project whose server is down, the SessionStart hook spawns
# `brainpalace start --json` detached (server + headless dashboard, no browser).
# CLI/plugin-side behavior, not a control-plane concern, so it lives under `cli`
# and is not surfaced in the dashboard (the parity gate does not enumerate the
# `cli` section). Disable via session_autostart:false or
# BRAINPALACE_SESSION_AUTOSTART=off.
# Nested `cli.subagent_guard.*` — gates Agent/Task spawns so subagents are forced
# to search via BrainPalace instead of grep/find. CLI/plugin-side enforcement
# (PreToolUse hook); not a server control-plane concern, so it lives under `cli`
# and is intentionally not surfaced in the dashboard (the parity gate does not
# enumerate the `cli` section). Default ON but active only in indexed projects;
# default mode `advisory` (nudge) — opt into `enforce` (deny) per project. Disable
# via enabled:false or BRAINPALACE_SUBAGENT_GUARD=off.
SUBAGENT_GUARD_KNOWN_FIELDS = {"enabled", "mode", "allow_agents"}
# Nested `cli.search_guard.*` — sibling of subagent_guard, gating the main
# thread's own Grep/Glob (PreToolUse hook) so it searches via BrainPalace instead
# of grep/glob. CLI/plugin-side enforcement, not a server control-plane concern,
# so it lives under `cli` and is not surfaced in the dashboard. Default ON,
# active only in indexed projects with a live server; default mode `advisory`
# (nudge) — opt into `enforce` (deny). Disable via enabled:false or
# BRAINPALACE_SEARCH_GUARD=off. Bash is not guarded (escape hatch for raw search).
SEARCH_GUARD_KNOWN_FIELDS = {"enabled", "mode"}
VALID_GUARD_MODES = {"advisory", "enforce"}
# Control-plane (dashboard process) settings — global only. Mirrors
# brainpalace_dashboard.config.DashboardConfig.
DASHBOARD_KNOWN_FIELDS = {
    "host",
    "port",
    "poll_s",
    "token",
    "autostart",
    "time_format",
    "date_format",
}
BM25_KNOWN_FIELDS = {"language", "engine", "detect", "detect_min_confidence"}
GIT_INDEXING_KNOWN_FIELDS = {
    "enabled",
    "depth",
    "max_files",
    "repo_path",
    "path_filter",
}
SESSION_INDEXING_KNOWN_FIELDS = {
    "enabled",
    "include_user_turns",
    "retain_days",
    "window",
    "stride",
    "watch_debounce_ms",
    "sessions_dir",
    "archive",
}
SESSION_EXTRACTION_KNOWN_FIELDS = {"quiescence_seconds"}
# `extraction:` section — shared engine for doc-graph triplets + session
# distillation (Plan 4). Mirrors ExtractionConfig in extraction_config.py.
EXTRACTION_KNOWN_FIELDS = {
    "mode",
    "grace_hours",
    "drain_batch_size",
    "drain_cooldown_seconds",
    "drain_doc_max_per_turn",
    "drain_session_max_per_turn",
    "max_provider_items_per_hour",
    "provider_session_max_chunks",
    "provider_context_tokens",
    "distill_chunk_chars",
    "max_pending",
}
INDEXING_KNOWN_FIELDS = {
    "reembed_cooldown_seconds",
    "big_file_chunks",
    "max_file_bytes_throttle",
    "skip_minified",
    "max_embed_tokens_per_job",
    "exclude_patterns",
}
# `usage_metrics:` section — mirrors UsageMetricsConfig in usage_metrics_config.py.
# retain_days <= 0 means keep forever (no ge= lower bound), so no _RANGE_RULES entry.
USAGE_METRICS_KNOWN_FIELDS = {"enabled", "retain_days"}

# ---------------------------------------------------------------------------
# Deprecated key mapping: dot-path -> migration suggestion
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Numeric range rules (Phase 5 — validation hardening). dot-path ->
# (min | None, max | None, message). Mirrors the server pydantic constraints so
# the shared validator rejects bad values inline at save instead of at runtime.
# Type errors are reported separately (type_fields); the range pass skips
# non-numeric values to avoid duplicate errors.
# ---------------------------------------------------------------------------

_PORT_RANGE = (1, 65535)

_RANGE_RULES: dict[str, tuple[float | None, float | None, str]] = {
    # Ports
    "bind.port_range_start": (
        *_PORT_RANGE,
        "bind.port_range_start must be between 1 and 65535",
    ),
    "bind.port_range_end": (
        *_PORT_RANGE,
        "bind.port_range_end must be between 1 and 65535",
    ),
    "storage.postgres.port": (
        *_PORT_RANGE,
        "storage.postgres.port must be between 1 and 65535",
    ),
    # Confidence
    "bm25.detect_min_confidence": (
        0.0,
        1.0,
        "bm25.detect_min_confidence must be between 0.0 and 1.0",
    ),
    "compute.min_confidence": (
        0.0,
        1.0,
        "compute.min_confidence must be between 0.0 and 1.0",
    ),
    # Non-negative counts / durations
    "query_log.retention_days": (0, None, "query_log.retention_days must be >= 0"),
    "git_indexing.depth": (0, None, "git_indexing.depth must be >= 0"),
    "git_indexing.max_files": (0, None, "git_indexing.max_files must be >= 0"),
    "session_indexing.retain_days": (
        0,
        None,
        "session_indexing.retain_days must be >= 0",
    ),
    "session_indexing.window": (0, None, "session_indexing.window must be >= 0"),
    "session_indexing.stride": (0, None, "session_indexing.stride must be >= 0"),
    "session_indexing.watch_debounce_ms": (
        0,
        None,
        "session_indexing.watch_debounce_ms must be >= 0",
    ),
    "session_extraction.quiescence_seconds": (
        0,
        None,
        "session_extraction.quiescence_seconds must be >= 0",
    ),
    # extraction.* — shared engine config (Plan 4)
    "extraction.grace_hours": (0, None, "extraction.grace_hours must be >= 0"),
    "extraction.drain_batch_size": (
        1,
        None,
        "extraction.drain_batch_size must be >= 1",
    ),
    "extraction.drain_cooldown_seconds": (
        0,
        None,
        "extraction.drain_cooldown_seconds must be >= 0",
    ),
    "extraction.drain_doc_max_per_turn": (
        0,
        None,
        "extraction.drain_doc_max_per_turn must be >= 0",
    ),
    "extraction.drain_session_max_per_turn": (
        0,
        None,
        "extraction.drain_session_max_per_turn must be >= 0",
    ),
    "extraction.max_provider_items_per_hour": (
        0,
        None,
        "extraction.max_provider_items_per_hour must be >= 0",
    ),
    "extraction.provider_session_max_chunks": (
        0,
        None,
        "extraction.provider_session_max_chunks must be >= 0",
    ),
    "extraction.provider_context_tokens": (
        0,
        None,
        "extraction.provider_context_tokens must be >= 0",
    ),
    "extraction.distill_chunk_chars": (
        0,
        None,
        "extraction.distill_chunk_chars must be >= 0",
    ),
    "extraction.max_pending": (0, None, "extraction.max_pending must be >= 0"),
    "indexing.reembed_cooldown_seconds": (
        0,
        None,
        "indexing.reembed_cooldown_seconds must be >= 0",
    ),
    "indexing.big_file_chunks": (0, None, "indexing.big_file_chunks must be >= 0"),
    "indexing.max_file_bytes_throttle": (
        0,
        None,
        "indexing.max_file_bytes_throttle must be >= 0",
    ),
}


def _get_dotpath(config: dict[str, Any], dotpath: str) -> Any:
    """Walk a dot-path through nested dicts; return None if any segment misses."""
    node: Any = config
    for segment in dotpath.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


DEPRECATED_KEYS: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Schema: section name -> (known_fields, enum_fields)
# ---------------------------------------------------------------------------

_SECTION_SCHEMA: dict[str, dict[str, Any]] = {
    "embedding": {
        "known_fields": EMBEDDING_KNOWN_FIELDS,
        "enum_fields": {
            "provider": (
                VALID_EMBEDDING_PROVIDERS,
                "Invalid embedding provider",
                f"Use one of: {', '.join(sorted(VALID_EMBEDDING_PROVIDERS))}",
            ),
        },
        "type_fields": {},
    },
    "summarization": {
        "known_fields": SUMMARIZATION_KNOWN_FIELDS,
        "enum_fields": {
            "provider": (
                VALID_SUMMARIZATION_PROVIDERS,
                "Invalid summarization provider",
                f"Use one of: {', '.join(sorted(VALID_SUMMARIZATION_PROVIDERS))}",
            ),
        },
        "type_fields": {},
    },
    "reranker": {
        "known_fields": RERANKER_KNOWN_FIELDS,
        "enum_fields": {
            "provider": (
                VALID_RERANKER_PROVIDERS,
                "Invalid reranker provider",
                f"Use one of: {', '.join(sorted(VALID_RERANKER_PROVIDERS))}",
            ),
        },
        "type_fields": {
            "enabled": (bool, "reranker.enabled must be a boolean (true/false)"),
        },
    },
    "storage": {
        "known_fields": STORAGE_KNOWN_FIELDS,
        "enum_fields": {
            "backend": (
                VALID_STORAGE_BACKENDS,
                "Invalid storage backend",
                f"Use one of: {', '.join(sorted(VALID_STORAGE_BACKENDS))}",
            ),
        },
        "type_fields": {},
    },
    "graphrag": {
        "known_fields": GRAPHRAG_KNOWN_FIELDS,
        "enum_fields": {
            "store_type": (
                VALID_GRAPHRAG_STORE_TYPES,
                "Invalid graphrag store_type",
                f"Use one of: {', '.join(sorted(VALID_GRAPHRAG_STORE_TYPES))}",
            ),
        },
        "type_fields": {
            "enabled": (bool, "graphrag.enabled must be a boolean (true/false)"),
            "use_code_metadata": (
                bool,
                "graphrag.use_code_metadata must be a boolean (true/false)",
            ),
        },
    },
    "compute": {
        "known_fields": COMPUTE_KNOWN_FIELDS,
        "enum_fields": {},
        # `min_confidence` (float) is intentionally not a type_field — it is range-
        # checked via _RANGE_RULES instead, mirroring bm25.detect_min_confidence,
        # so an integer YAML value like `1` is not falsely rejected by isinstance.
        "type_fields": {},
    },
    "bind": {
        "known_fields": BIND_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "port_range_start": (int, "bind.port_range_start must be an integer"),
            "port_range_end": (int, "bind.port_range_end must be an integer"),
            "auto_port": (bool, "bind.auto_port must be a boolean (true/false)"),
        },
    },
    "server": {
        "known_fields": SERVER_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "read_only": (bool, "server.read_only must be a boolean (true/false)"),
        },
    },
    "query_log": {
        "known_fields": QUERY_LOG_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "enabled": (bool, "query_log.enabled must be a boolean (true/false)"),
            "retention_days": (int, "query_log.retention_days must be an integer"),
        },
    },
    "dashboard": {
        "known_fields": DASHBOARD_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "port": (int, "dashboard.port must be an integer"),
            "poll_s": (int, "dashboard.poll_s must be an integer"),
            "autostart": (bool, "dashboard.autostart must be a boolean (true/false)"),
        },
    },
    "cli": {
        "known_fields": CLI_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "show_ai_hint": (
                bool,
                "cli.show_ai_hint must be a boolean (true/false)",
            ),
            "session_autostart": (
                bool,
                "cli.session_autostart must be a boolean (true/false)",
            ),
            "await_first_start": (
                bool,
                "cli.await_first_start must be a boolean (true/false)",
            ),
        },
    },
    "bm25": {
        "known_fields": BM25_KNOWN_FIELDS,
        "enum_fields": {
            "engine": (
                VALID_BM25_ENGINES,
                "Invalid bm25 engine",
                f"Use one of: {', '.join(sorted(VALID_BM25_ENGINES))}",
            ),
        },
        "type_fields": {
            "detect": (bool, "bm25.detect must be a boolean (true/false)"),
        },
    },
    "git_indexing": {
        "known_fields": GIT_INDEXING_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "enabled": (bool, "git_indexing.enabled must be a boolean (true/false)"),
            "depth": (int, "git_indexing.depth must be an integer"),
            "max_files": (int, "git_indexing.max_files must be an integer"),
        },
    },
    "session_indexing": {
        "known_fields": SESSION_INDEXING_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "enabled": (
                bool,
                "session_indexing.enabled must be a boolean (true/false)",
            ),
            "include_user_turns": (
                bool,
                "session_indexing.include_user_turns must be a boolean (true/false)",
            ),
            "retain_days": (int, "session_indexing.retain_days must be an integer"),
            "window": (int, "session_indexing.window must be an integer"),
            "stride": (int, "session_indexing.stride must be an integer"),
            "watch_debounce_ms": (
                int,
                "session_indexing.watch_debounce_ms must be an integer",
            ),
        },
    },
    "session_extraction": {
        "known_fields": SESSION_EXTRACTION_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "quiescence_seconds": (
                int,
                "session_extraction.quiescence_seconds must be an integer",
            ),
        },
    },
    # Plan 4: shared extraction engine — governs doc-graph triplets AND session
    # distillation. mode enum validated; int fields range-checked via _RANGE_RULES.
    "extraction": {
        "known_fields": EXTRACTION_KNOWN_FIELDS,
        "enum_fields": {
            "mode": (
                VALID_EXTRACT_MODES,
                "Invalid extraction mode",
                f"Use one of: {', '.join(sorted(VALID_EXTRACT_MODES))}",
            ),
        },
        "type_fields": {
            "grace_hours": (int, "extraction.grace_hours must be an integer"),
            "drain_batch_size": (int, "extraction.drain_batch_size must be an integer"),
            "drain_cooldown_seconds": (
                int,
                "extraction.drain_cooldown_seconds must be an integer",
            ),
            "drain_doc_max_per_turn": (
                int,
                "extraction.drain_doc_max_per_turn must be an integer",
            ),
            "drain_session_max_per_turn": (
                int,
                "extraction.drain_session_max_per_turn must be an integer",
            ),
            "max_provider_items_per_hour": (
                int,
                "extraction.max_provider_items_per_hour must be an integer",
            ),
            "provider_session_max_chunks": (
                int,
                "extraction.provider_session_max_chunks must be an integer",
            ),
            "provider_context_tokens": (
                int,
                "extraction.provider_context_tokens must be an integer",
            ),
            "distill_chunk_chars": (
                int,
                "extraction.distill_chunk_chars must be an integer",
            ),
            "max_pending": (int, "extraction.max_pending must be an integer"),
        },
    },
    "indexing": {
        "known_fields": INDEXING_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "reembed_cooldown_seconds": (
                int,
                "indexing.reembed_cooldown_seconds must be an integer",
            ),
            "big_file_chunks": (int, "indexing.big_file_chunks must be an integer"),
            "max_file_bytes_throttle": (
                int,
                "indexing.max_file_bytes_throttle must be an integer",
            ),
            "skip_minified": (
                bool,
                "indexing.skip_minified must be a boolean (true/false)",
            ),
        },
    },
    # Plan 5: usage/spend telemetry — two fields, no enums, retain_days has no
    # lower-bound range rule (<=0 = keep forever, §6-F1).
    "usage_metrics": {
        "known_fields": USAGE_METRICS_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "enabled": (
                bool,
                "usage_metrics.enabled must be a boolean (true/false)",
            ),
            "retain_days": (int, "usage_metrics.retain_days must be an integer"),
        },
    },
}


# ---------------------------------------------------------------------------
# ConfigValidationError dataclass
# ---------------------------------------------------------------------------


@dataclass
class ConfigValidationError:
    """A single validation error found in a config.yaml file.

    Attributes:
        field: Dot-path to the offending field, e.g. "embedding.provider".
        message: Human-readable description of the problem.
        line_number: Approximate 1-indexed line in the YAML file, or None if
            the error was produced from a dict (no source text available).
        suggestion: Actionable fix text shown to the user.
    """

    field: str
    message: str
    line_number: int | None
    suggestion: str = dc_field(default="")


# ---------------------------------------------------------------------------
# Line-number helper
# ---------------------------------------------------------------------------


def _find_line_number(yaml_text: str, key_path: str) -> int | None:
    """Scan YAML text to find the approximate line of a dot-path key.

    Strategy: split key_path by ".", search for each segment starting from
    the line after the parent was found.  Returns a 1-indexed line number.

    Args:
        yaml_text: Raw YAML file content.
        key_path: Dot-separated key path, e.g. "embedding.provider".

    Returns:
        1-indexed line number, or None if not found.
    """
    segments = key_path.split(".")
    lines = yaml_text.splitlines()
    search_from = 0

    for segment in segments:
        found_at: int | None = None
        for i in range(search_from, len(lines)):
            stripped = lines[i].lstrip()
            # Match "segment:" or "segment :" at the start of a stripped line
            if stripped.startswith(f"{segment}:") or stripped == segment:
                found_at = i
                break
        if found_at is None:
            return None
        search_from = found_at + 1

    # Return 1-indexed line of the deepest segment
    if search_from > 0:
        return search_from  # search_from = found_at + 1, so this is 1-indexed
    return None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def validate_config_dict(
    config: dict[str, Any],
) -> list[ConfigValidationError]:
    """Validate a config dict against the BrainPalace schema.

    Does NOT enrich errors with line numbers — that is done by
    :func:`validate_config_file`.

    Args:
        config: Parsed YAML config dictionary.

    Returns:
        List of :class:`ConfigValidationError` objects (empty if valid).
    """
    errors: list[ConfigValidationError] = []

    # 1. Check for unknown top-level keys
    for key in config:
        if key not in VALID_TOP_LEVEL_KEYS:
            errors.append(
                ConfigValidationError(
                    field=key,
                    message=f"Unknown top-level key '{key}'",
                    line_number=None,
                    suggestion=(
                        f"Remove or rename '{key}'. "
                        f"Valid keys: {', '.join(sorted(VALID_TOP_LEVEL_KEYS))}"
                    ),
                )
            )

    # 2. Per-section validation
    for section_name, schema in _SECTION_SCHEMA.items():
        section_data = config.get(section_name)
        if section_data is None:
            continue  # Section not present — that's fine, all sections optional
        if not isinstance(section_data, dict):
            actual_type = type(section_data).__name__
            errors.append(
                ConfigValidationError(
                    field=section_name,
                    message=(
                        f"'{section_name}' must be a mapping (dict),"
                        f" got {actual_type}"
                    ),
                    line_number=None,
                    suggestion=(
                        f"Ensure '{section_name}:' is followed by"
                        " indented key-value pairs."
                    ),
                )
            )
            continue

        known_fields: set[str] = schema["known_fields"]
        enum_fields: dict[str, tuple[set[str], str, str]] = schema["enum_fields"]
        type_fields: dict[str, tuple[type, str]] = schema["type_fields"]

        # 2a. Unknown sub-keys
        for sub_key in section_data:
            if sub_key not in known_fields:
                errors.append(
                    ConfigValidationError(
                        field=f"{section_name}.{sub_key}",
                        message=f"Unknown key '{sub_key}' in section '{section_name}'",
                        line_number=None,
                        suggestion=(
                            f"Remove '{sub_key}' or check for a typo. "
                            f"Known fields: {', '.join(sorted(known_fields))}"
                        ),
                    )
                )

        # 2b. Enum field validation
        for enum_key, (valid_values, msg, suggestion) in enum_fields.items():
            value = section_data.get(enum_key)
            if value is not None and str(value) not in valid_values:
                errors.append(
                    ConfigValidationError(
                        field=f"{section_name}.{enum_key}",
                        message=f"{msg}: '{value}'",
                        line_number=None,
                        suggestion=suggestion,
                    )
                )

        # 2c. Type validation
        for type_key, (expected_type, type_msg) in type_fields.items():
            value = section_data.get(type_key)
            if value is not None and not isinstance(value, expected_type):
                errors.append(
                    ConfigValidationError(
                        field=f"{section_name}.{type_key}",
                        message=type_msg,
                        line_number=None,
                        suggestion=(
                            f"Change '{type_key}' to a"
                            f" {expected_type.__name__} value."
                        ),
                    )
                )

    # 2d. Nested storage.postgres.* key validation
    storage_section = config.get("storage")
    if isinstance(storage_section, dict):
        postgres_data = storage_section.get("postgres")
        if isinstance(postgres_data, dict):
            for pg_key in postgres_data:
                if pg_key not in POSTGRES_KNOWN_FIELDS:
                    errors.append(
                        ConfigValidationError(
                            field=f"storage.postgres.{pg_key}",
                            message=f"Unknown key '{pg_key}' in storage.postgres",
                            line_number=None,
                            suggestion=(
                                f"Remove '{pg_key}' or check for a typo. "
                                "Known fields: "
                                f"{', '.join(sorted(POSTGRES_KNOWN_FIELDS))}"
                            ),
                        )
                    )
            # Type validation for postgres sub-keys
            for type_key, (expected_type, type_msg) in POSTGRES_TYPE_FIELDS.items():
                value = postgres_data.get(type_key)
                if value is not None and not isinstance(value, expected_type):
                    errors.append(
                        ConfigValidationError(
                            field=f"storage.postgres.{type_key}",
                            message=type_msg,
                            line_number=None,
                            suggestion=(
                                f"Change '{type_key}' to a"
                                f" {expected_type.__name__} value."
                            ),
                        )
                    )

    # 2d-bis. Nested cli.subagent_guard.* key validation.
    cli_section = config.get("cli")
    if isinstance(cli_section, dict):
        guard_data = cli_section.get("subagent_guard")
        if isinstance(guard_data, dict):
            for g_key in guard_data:
                if g_key not in SUBAGENT_GUARD_KNOWN_FIELDS:
                    errors.append(
                        ConfigValidationError(
                            field=f"cli.subagent_guard.{g_key}",
                            message=f"Unknown key '{g_key}' in cli.subagent_guard",
                            line_number=None,
                            suggestion=(
                                f"Remove '{g_key}' or check for a typo. "
                                "Known fields: "
                                f"{', '.join(sorted(SUBAGENT_GUARD_KNOWN_FIELDS))}"
                            ),
                        )
                    )
            enabled = guard_data.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                errors.append(
                    ConfigValidationError(
                        field="cli.subagent_guard.enabled",
                        message=(
                            "cli.subagent_guard.enabled must be a boolean (true/false)"
                        ),
                        line_number=None,
                        suggestion="Change 'enabled' to a bool value.",
                    )
                )
            mode = guard_data.get("mode")
            if mode is not None and str(mode) not in VALID_GUARD_MODES:
                errors.append(
                    ConfigValidationError(
                        field="cli.subagent_guard.mode",
                        message=f"Invalid cli.subagent_guard.mode: '{mode}'",
                        line_number=None,
                        suggestion=(
                            f"Use one of: {', '.join(sorted(VALID_GUARD_MODES))}"
                        ),
                    )
                )
            allow = guard_data.get("allow_agents")
            if allow is not None and not isinstance(allow, list):
                errors.append(
                    ConfigValidationError(
                        field="cli.subagent_guard.allow_agents",
                        message=(
                            "cli.subagent_guard.allow_agents must be a list of "
                            "agent names"
                        ),
                        line_number=None,
                        suggestion="Use a YAML list, e.g. [research, setup].",
                    )
                )

        # 2d-ter. Nested cli.search_guard.* key validation (sibling of above).
        search_data = cli_section.get("search_guard")
        if isinstance(search_data, dict):
            for s_key in search_data:
                if s_key not in SEARCH_GUARD_KNOWN_FIELDS:
                    errors.append(
                        ConfigValidationError(
                            field=f"cli.search_guard.{s_key}",
                            message=f"Unknown key '{s_key}' in cli.search_guard",
                            line_number=None,
                            suggestion=(
                                f"Remove '{s_key}' or check for a typo. "
                                "Known fields: "
                                f"{', '.join(sorted(SEARCH_GUARD_KNOWN_FIELDS))}"
                            ),
                        )
                    )
            s_enabled = search_data.get("enabled")
            if s_enabled is not None and not isinstance(s_enabled, bool):
                errors.append(
                    ConfigValidationError(
                        field="cli.search_guard.enabled",
                        message=(
                            "cli.search_guard.enabled must be a boolean (true/false)"
                        ),
                        line_number=None,
                        suggestion="Change 'enabled' to a bool value.",
                    )
                )
            s_mode = search_data.get("mode")
            if s_mode is not None and str(s_mode) not in VALID_GUARD_MODES:
                errors.append(
                    ConfigValidationError(
                        field="cli.search_guard.mode",
                        message=f"Invalid cli.search_guard.mode: '{s_mode}'",
                        line_number=None,
                        suggestion=(
                            f"Use one of: {', '.join(sorted(VALID_GUARD_MODES))}"
                        ),
                    )
                )

    # 2e. Numeric range validation (Phase 5). Skips non-numeric values so a type
    # error (reported above) does not also produce a range error.
    for dotpath, (lo, hi, range_msg) in _RANGE_RULES.items():
        value = _get_dotpath(config, dotpath)
        if value is None or isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue  # type mismatch already reported by type_fields
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            errors.append(
                ConfigValidationError(
                    field=dotpath,
                    message=range_msg,
                    line_number=None,
                    suggestion=f"Set {dotpath} within the allowed range.",
                )
            )

    # 3. Check deprecated keys
    for deprecated_path, migration_hint in DEPRECATED_KEYS.items():
        parts = deprecated_path.split(".", 1)
        section_name = parts[0]
        sub_key = parts[1] if len(parts) > 1 else ""
        section_data = config.get(section_name)
        if isinstance(section_data, dict) and sub_key in section_data:
            errors.append(
                ConfigValidationError(
                    field=deprecated_path,
                    message=f"Deprecated key '{deprecated_path}'",
                    line_number=None,
                    suggestion=migration_hint,
                )
            )

    return errors


def validate_config_file(path: Path) -> list[ConfigValidationError]:
    """Validate a config.yaml file against the BrainPalace schema.

    Reads the file as raw text, parses with yaml.safe_load, calls
    :func:`validate_config_dict`, then enriches each error with a line number
    using :func:`_find_line_number`.

    Args:
        path: Path to the YAML config file.

    Returns:
        List of :class:`ConfigValidationError` objects (empty if valid).

    Raises:
        OSError: If the file cannot be read.
        yaml.YAMLError: If the YAML cannot be parsed.
    """
    yaml_text = path.read_text(encoding="utf-8")
    config: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    errors = validate_config_dict(config)
    # Enrich with line numbers
    for error in errors:
        if error.line_number is None:
            error.line_number = _find_line_number(yaml_text, error.field)
    return errors


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_validation_errors(errors: list[ConfigValidationError]) -> str:
    """Format a list of validation errors into a human-readable string.

    Example output::

        Config validation errors:

          Line 3: embedding.provider = "badprovider"
            Error: Invalid embedding provider: 'badprovider'
            Fix: Use one of: cohere, ollama, openai

    Args:
        errors: List of :class:`ConfigValidationError` objects.

    Returns:
        Formatted multi-line string.
    """
    if not errors:
        return ""

    lines = ["Config validation errors:", ""]
    for error in errors:
        if error.line_number is not None:
            header = f"  Line {error.line_number}: {error.field}"
        else:
            header = f"  {error.field}"
        lines.append(header)
        lines.append(f"    Error: {error.message}")
        if error.suggestion:
            lines.append(f"    Fix: {error.suggestion}")
        lines.append("")
    return "\n".join(lines)


# --- Activation gate marker (cli.await_first_start) -------------------------
#
# `cli.await_first_start: true` marks a project configured by the PLUGIN path
# (`brainpalace init --defer-activation`) that the user has NOT yet started
# manually. While set, PASSIVE start vectors (the SessionStart hook and
# `brainpalace mcp --ensure-server`) must NOT spawn a server — only an explicit
# `brainpalace start` (or dashboard Instances -> Start) activates the project,
# which clears the marker. Terminal `brainpalace init` (no flag) never writes it.
def read_await_first_start(state_dir: Path) -> bool:
    """True if the project at ``state_dir`` is configured but awaiting first start.

    Reads ``cli.await_first_start`` from ``state_dir/config.yaml``. Best-effort:
    any read/parse error returns False (fail toward allowing a start — never
    block a project that has no marker).
    """
    try:
        config_path = state_dir / "config.yaml"
        if not config_path.is_file():
            return False
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cli = data.get("cli")
        return bool(isinstance(cli, dict) and cli.get("await_first_start") is True)
    except (OSError, ValueError):
        return False


def write_await_first_start(state_dir: Path, value: bool) -> None:
    """Set or clear ``cli.await_first_start`` in ``state_dir/config.yaml`` (sparse).

    ``value=True`` writes the marker; ``value=False`` REMOVES the key (and an
    emptied ``cli`` block) so the config stays sparse and the field inherits its
    default. Preserves all other keys. Best-effort: errors are swallowed — the
    marker is an optimisation, never a hard dependency.
    """
    try:
        config_path = state_dir / "config.yaml"
        data: dict[str, Any] = {}
        if config_path.exists():
            try:
                data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                data = {}
        cli = data.get("cli")
        if not isinstance(cli, dict):
            cli = {}
        if value:
            cli["await_first_start"] = True
        else:
            cli.pop("await_first_start", None)
        if cli:
            data["cli"] = cli
        else:
            data.pop("cli", None)
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    except OSError:
        pass


def resolve_session_autostart(state_dir: Path | None) -> bool:
    """Resolve ``cli.session_autostart`` (global XDG + project, project wins).

    Env override ``BRAINPALACE_SESSION_AUTOSTART`` (off|on) takes top precedence.
    Default ``True``. Best-effort: any failure returns the default so callers fail
    toward the documented on-by-default behaviour. ``state_dir`` supplies the
    project layer; pass ``None`` to consult only the global config.
    """
    import os

    env = os.getenv("BRAINPALACE_SESSION_AUTOSTART", "").strip().lower()
    if env in ("off", "false", "0", "disabled"):
        return False
    if env in ("on", "true", "1", "enabled"):
        return True
    from .xdg_paths import get_xdg_config_dir

    enabled = True
    candidates: list[Path] = [get_xdg_config_dir() / "config.yaml"]
    if state_dir is not None:
        candidates.append(state_dir / "config.yaml")
    for path in candidates:
        try:
            if path.is_file():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                cli = data.get("cli")
                if isinstance(cli, dict) and isinstance(
                    cli.get("session_autostart"), bool
                ):
                    enabled = cli["session_autostart"]
        except (OSError, ValueError):
            continue
    return enabled


def passive_autostart_allowed(state_dir: Path) -> bool:
    """Single chokepoint: may a PASSIVE vector spawn a server for this project?

    True only when session-autostart is enabled AND the project is not awaiting
    its first manual start (the activation gate). Both passive callers — the
    SessionStart hook and the MCP ``--ensure-server`` lifecycle — funnel through
    here, so any future passive vector inherits the gate for free. Manual callers
    (``brainpalace start``, the dashboard "Start" action) bypass this entirely:
    they start unconditionally and CLEAR the marker (activation event).
    """
    if read_await_first_start(state_dir):
        return False
    return resolve_session_autostart(state_dir)
