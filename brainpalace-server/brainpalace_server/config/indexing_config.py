"""Phase L — per-project ``indexing:`` config block (large-file re-embed guard).

A large, frequently-changing file (build artifacts, minified bundles, logs, data
dumps) gets fully re-embedded on every change → runaway embedding cost. This block
holds the knobs for the path-agnostic anti-churn guard:

- ``reembed_cooldown_seconds`` — min seconds between re-embeds of a LARGE file
  (0 = off). A large file that changed within the cooldown is *deferred* (its
  existing chunks are kept, not re-embedded) so it costs at most one re-embed per
  cooldown window. Defaults ON.
- ``big_file_chunks`` / ``max_file_bytes_throttle`` — thresholds that mark a file
  "large" (prior chunk-count OR byte size).
- ``skip_minified`` — skip single-line / minified blobs entirely at load time.

Env overrides: ``REEMBED_COOLDOWN_SECONDS``, ``INDEX_BIG_FILE_CHUNKS``,
``INDEX_MAX_FILE_BYTES``, ``INDEX_SKIP_MINIFIED``, ``INDEX_MAX_EMBED_TOKENS``,
``INDEX_MAX_EMBED_RATIO``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import load_raw_config

logger = logging.getLogger(__name__)


class IndexingConfig(BaseModel):
    """Parsed ``indexing:`` section. Defaults are the locked Phase L values."""

    reembed_cooldown_seconds: int = Field(
        default=3600,
        ge=0,
        description=(
            "Min seconds between re-embeds of a LARGE file (0 = off). A large "
            "file changing faster than this is deferred (chunks kept, not "
            "re-embedded) until the cooldown elapses."
        ),
    )
    big_file_chunks: int = Field(
        default=200,
        ge=0,
        description="Prior chunk-count that marks a file 'large' for the throttle.",
    )
    max_file_bytes_throttle: int = Field(
        default=262144,
        ge=0,
        description="File byte size (default 256 KB) that marks a file 'large'.",
    )
    skip_minified: bool = Field(
        default=True,
        description="Skip single-line / minified blobs (*.min.js, *.min.css) entirely.",
    )
    max_embed_tokens_per_job: int = Field(
        default=100_000,
        ge=0,
        description=(
            "Hard cap on embedding tokens per index job. 0 disables the guard. "
            "Over the cap the job fails with a budget error unless force_budget. "
            "A folder's FIRST index is always exempt — the cap guards re-indexes, "
            "not the deliberate initial index."
        ),
    )
    max_embed_ratio_per_job: float = Field(
        default=0.2,
        ge=0.0,
        description=(
            "Adaptive extension of the token cap: the effective per-job cap is "
            "max(max_embed_tokens_per_job, this ratio × estimated index size "
            "in tokens). 0 disables the adaptive part (pure fixed cap). Index "
            "size is approximated as total chunks × chunk_size. Ignored when "
            "max_embed_tokens_per_job is 0 (guard fully disabled), and moot on a "
            "folder's first index (always exempt — the store is still near-empty)."
        ),
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/__pycache__/**",
            "**/.venv/**",
            "**/venv/**",
            "**/.git/**",
            "**/dist/**",
            "**/build/**",
            "**/target/**",
            "**/.next/**",
            "**/.nuxt/**",
            "**/coverage/**",
            "**/.pytest_cache/**",
            "**/.mypy_cache/**",
            "**/.tox/**",
            "**/egg-info/**",
            "**/*.egg-info/**",
            "**/.claude/**",
            "**/.claude-plugin/**",
            "**/.brainpalace/**",
        ],
        description=(
            "Glob patterns excluded from indexing (one per row). Matches both "
            "directories (prunes the subtree) and individual files, so a single "
            "file can be excluded, e.g. '**/docs/CHANGELOG.md'. Use '**/' to "
            "match at any depth. Project-configured patterns are ADDED to this "
            "built-in default list (they extend it, never replace it), so adding "
            "one pattern never drops the defaults."
        ),
    )


def _env_int(name: str, current: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return current
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r", name, raw)
        return current


def _env_float(name: str, current: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return current
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning("Ignoring non-float %s=%r", name, raw)
        return current


def _env_bool(name: str, current: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return current
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_indexing_config(config_path: Path | None = None) -> IndexingConfig:
    """Load the ``indexing:`` block, or defaults if absent. Env overrides win."""
    cfg = IndexingConfig()
    default_excludes = cfg.exclude_patterns
    try:
        raw = load_raw_config(config_path)
        block = raw.get("indexing")
        if isinstance(block, dict):
            fields = {
                k: v for k, v in block.items() if k in IndexingConfig.model_fields
            }
            cfg = IndexingConfig(**fields)
            if "exclude_patterns" in fields:
                # Additive: project patterns EXTEND the built-in defaults instead
                # of replacing them, so adding one file pattern never silently
                # drops node_modules/.venv/.claude/.brainpalace exclusion. Order:
                # defaults first, then project extras, de-duplicated.
                seen = set(default_excludes)
                merged = list(default_excludes) + [
                    p for p in cfg.exclude_patterns if p not in seen
                ]
                cfg = cfg.model_copy(update={"exclude_patterns": merged})
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("Could not parse indexing config: %s", exc)

    return cfg.model_copy(
        update={
            "reembed_cooldown_seconds": _env_int(
                "REEMBED_COOLDOWN_SECONDS", cfg.reembed_cooldown_seconds
            ),
            "big_file_chunks": _env_int("INDEX_BIG_FILE_CHUNKS", cfg.big_file_chunks),
            "max_file_bytes_throttle": _env_int(
                "INDEX_MAX_FILE_BYTES", cfg.max_file_bytes_throttle
            ),
            "skip_minified": _env_bool("INDEX_SKIP_MINIFIED", cfg.skip_minified),
            "max_embed_tokens_per_job": _env_int(
                "INDEX_MAX_EMBED_TOKENS", cfg.max_embed_tokens_per_job
            ),
            "max_embed_ratio_per_job": _env_float(
                "INDEX_MAX_EMBED_RATIO", cfg.max_embed_ratio_per_job
            ),
        }
    )
