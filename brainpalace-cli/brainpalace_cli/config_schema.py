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
    "api",
    "server",
    "project",
    "query_log",
    "bm25",
    "git_indexing",
    "session_indexing",
    "session_extraction",
    "indexing",
    "dashboard",
    "cli",
}

VALID_EMBEDDING_PROVIDERS = {"openai", "ollama", "cohere"}
VALID_SUMMARIZATION_PROVIDERS = {"anthropic", "openai", "ollama", "gemini", "grok"}
VALID_RERANKER_PROVIDERS = {"sentence-transformers", "ollama"}
VALID_STORAGE_BACKENDS = {"chroma", "postgres"}
VALID_GRAPHRAG_STORE_TYPES = {"simple", "sqlite"}
VALID_DOC_EXTRACTORS = {"langextract", "none"}
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
    "doc_extractor",
}
API_KNOWN_FIELDS = {"host", "port"}
SERVER_KNOWN_FIELDS = {"url", "host", "port", "auto_port", "read_only"}
PROJECT_KNOWN_FIELDS = {"state_dir", "project_root"}
QUERY_LOG_KNOWN_FIELDS = {"enabled", "retention_days"}
CLI_KNOWN_FIELDS = {"show_ai_hint"}
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
SESSION_EXTRACTION_KNOWN_FIELDS = {"mode", "quiescence_seconds"}
INDEXING_KNOWN_FIELDS = {
    "reembed_cooldown_seconds",
    "big_file_chunks",
    "max_file_bytes_throttle",
    "skip_minified",
}

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
    "api.port": (*_PORT_RANGE, "api.port must be between 1 and 65535"),
    "server.port": (*_PORT_RANGE, "server.port must be between 1 and 65535"),
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


DEPRECATED_KEYS: dict[str, str] = {
    "graphrag.use_llm_extraction": (
        "Renamed to 'graphrag.doc_extractor'. "
        "Use doc_extractor: langextract instead."
    ),
}

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
            "doc_extractor": (
                VALID_DOC_EXTRACTORS,
                "Invalid graphrag doc_extractor",
                f"Use one of: {', '.join(sorted(VALID_DOC_EXTRACTORS))}",
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
    "api": {
        "known_fields": API_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "port": (int, "api.port must be an integer"),
        },
    },
    "server": {
        "known_fields": SERVER_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {
            "port": (int, "server.port must be an integer"),
            "auto_port": (bool, "server.auto_port must be a boolean (true/false)"),
            "read_only": (bool, "server.read_only must be a boolean (true/false)"),
        },
    },
    "project": {
        "known_fields": PROJECT_KNOWN_FIELDS,
        "enum_fields": {},
        "type_fields": {},
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
        "enum_fields": {
            "mode": (
                VALID_EXTRACT_MODES,
                "Invalid session_extraction mode",
                f"Use one of: {', '.join(sorted(VALID_EXTRACT_MODES))}",
            ),
        },
        "type_fields": {
            "quiescence_seconds": (
                int,
                "session_extraction.quiescence_seconds must be an integer",
            ),
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
