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
``INDEX_MAX_FILE_BYTES``, ``INDEX_SKIP_MINIFIED``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file

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


def _env_int(name: str, current: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return current
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r", name, raw)
        return current


def _env_bool(name: str, current: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return current
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_indexing_config(config_path: Path | None = None) -> IndexingConfig:
    """Load the ``indexing:`` block, or defaults if absent. Env overrides win."""
    path = config_path or _find_config_file()
    cfg = IndexingConfig()
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            block = raw.get("indexing")
            if isinstance(block, dict):
                cfg = IndexingConfig(
                    **{
                        k: v
                        for k, v in block.items()
                        if k in IndexingConfig.model_fields
                    }
                )
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
        }
    )
