"""Phase 04 (dashboard) — per-project ``query_log:`` config.

The query log persists every successful query (with truncated results) to a
SQLite store under the project state dir, powering the dashboard "Queries" tab.
It is **ON by default** with a 7-day retention. The block lives in the project
``config.yaml``; an absent block uses the defaults. A global env kill-switch
(``QUERY_LOG_ENABLED=false``) hard-disables logging regardless of the block.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file

logger = logging.getLogger(__name__)


class QueryLogConfig(BaseModel):
    """Parsed ``query_log:`` section."""

    enabled: bool = Field(
        default=True, description="Persist queries to the per-project history log."
    )
    retention_days: int = Field(
        default=7,
        description="Purge query rows older than this on startup. <= 0 keeps forever.",
    )


def _env_master_enabled() -> bool:
    """Global kill-switch. Defaults to True (project block then decides)."""
    raw = os.getenv("QUERY_LOG_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_query_log_config(
    config_path: Path | None = None,
) -> QueryLogConfig:
    """Load the ``query_log:`` block, or defaults (enabled) if absent.

    ``QUERY_LOG_ENABLED=false`` forces ``enabled`` off even when the project
    opts in.
    """
    path = config_path or _find_config_file()
    cfg = QueryLogConfig()
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            block = raw.get("query_log")
            if isinstance(block, dict):
                cfg = QueryLogConfig(
                    **{
                        k: v
                        for k, v in block.items()
                        if k in QueryLogConfig.model_fields
                    }
                )
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("Could not parse query_log config: %s", exc)

    if not _env_master_enabled():
        cfg = cfg.model_copy(update={"enabled": False})
    return cfg
