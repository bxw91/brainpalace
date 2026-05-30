"""Phase 050 — per-project ``session_indexing:`` config.

Session indexing is **OFF by default** and strictly opt-in per project. The
block lives in the project ``config.yaml`` (same file the ``graphrag:`` block
uses); an absent block means disabled. A global env master switch
(``SESSION_INDEXING_ENABLED``) can hard-disable regardless of the project block.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file

logger = logging.getLogger(__name__)


class SessionIndexingConfig(BaseModel):
    """Parsed ``session_indexing:`` section. Defaults are privacy-first."""

    enabled: bool = Field(
        default=False, description="Opt in to indexing session transcripts."
    )
    include_user_turns: bool = Field(
        default=False,
        description="Index human user dialogue too (default: assistant/tools only).",
    )
    retain_days: int = Field(
        default=90,
        description="Sessions older than this are skipped (roll-up summary = 100).",
    )
    window: int = Field(default=4, description="Turns per sliding window (3-5).")
    stride: int = Field(default=2, description="Window stride in turns.")
    sessions_dir: str | None = Field(
        default=None,
        description="Override the auto-resolved runtime session directory.",
    )


def _env_master_enabled() -> bool:
    """Global kill-switch. Defaults to True (project block then decides)."""
    raw = os.getenv("SESSION_INDEXING_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_session_indexing_config(
    config_path: Path | None = None,
) -> SessionIndexingConfig:
    """Load the ``session_indexing:`` block, or defaults (disabled) if absent.

    The global ``SESSION_INDEXING_ENABLED=false`` env var forces ``enabled``
    off even when the project opts in.
    """
    path = config_path or _find_config_file()
    cfg = SessionIndexingConfig()
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            block = raw.get("session_indexing")
            if isinstance(block, dict):
                cfg = SessionIndexingConfig(**{
                    k: v for k, v in block.items()
                    if k in SessionIndexingConfig.model_fields
                })
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("Could not parse session_indexing config: %s", exc)

    if not _env_master_enabled():
        cfg = cfg.model_copy(update={"enabled": False})
    return cfg
