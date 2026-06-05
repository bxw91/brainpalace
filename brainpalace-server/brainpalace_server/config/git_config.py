"""Phase 130 — per-project ``git_indexing:`` config.

Git-history indexing is **OFF by default** and strictly opt-in per project,
mirroring 050 session indexing. Diffs can contain secrets, so the opt-in is
deliberate (see ``docs/GIT_HISTORY.md``). The block lives in the project
``config.yaml``; an absent block means disabled. A global env master switch
(``GIT_INDEXING_ENABLED``) can hard-disable regardless of the project block.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file

logger = logging.getLogger(__name__)


class GitIndexingConfig(BaseModel):
    """Parsed ``git_indexing:`` section. Defaults are privacy-first."""

    enabled: bool = Field(default=False, description="Opt in to indexing git history.")
    depth: int = Field(
        default=1000,
        description="Max commits walked on a full (first) index pass.",
    )
    max_files: int = Field(
        default=50,
        description="Max changed file paths rendered into a commit chunk.",
    )
    repo_path: str | None = Field(
        default=None,
        description="Override the repo to index (defaults to the project root).",
    )
    path_filter: list[str] = Field(
        default_factory=list,
        description=(
            "Repo-relative paths; when non-empty, only commits touching these "
            "paths are indexed (git log -- <paths>). Empty = all commits."
        ),
    )


def _env_master_enabled() -> bool:
    """Global kill-switch. Defaults to True (project block then decides)."""
    raw = os.getenv("GIT_INDEXING_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_git_indexing_config(
    config_path: Path | None = None,
) -> GitIndexingConfig:
    """Load the ``git_indexing:`` block, or defaults (disabled) if absent.

    The global ``GIT_INDEXING_ENABLED=false`` env var forces ``enabled`` off
    even when the project opts in.
    """
    path = config_path or _find_config_file()
    cfg = GitIndexingConfig()
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            block = raw.get("git_indexing")
            if isinstance(block, dict):
                cfg = GitIndexingConfig(
                    **{
                        k: v
                        for k, v in block.items()
                        if k in GitIndexingConfig.model_fields
                    }
                )
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("Could not parse git_indexing config: %s", exc)

    if not _env_master_enabled():
        cfg = cfg.model_copy(update={"enabled": False})
    return cfg
