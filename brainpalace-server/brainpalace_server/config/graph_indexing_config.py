"""Phase 150 (Plan 2) — per-project ``graph_indexing.lsp:`` config.

Promotes the legacy hidden flat flag ``BRAINPALACE_LSP_LANGUAGES`` to a proper
section model so the dashboard auto-renders a per-language LSP toggle. ``auto``
(the default) detects a language-server binary and enables LSP cross-references
when present; ``on`` forces the on-toggled languages; ``off`` disables. The
legacy env var still works as an override (see ``lsp/servers.enabled_languages``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from brainpalace_server.config.provider_config import load_raw_config

logger = logging.getLogger(__name__)

# YAML 1.1 parses bare `on`/`off`/`yes`/`no` as booleans; map back to strings
# so the user can write `mode: off` without quoting.
_BOOL_TO_MODE: dict[bool, str] = {True: "on", False: "off"}


class GraphLspConfig(BaseModel):
    """LSP cross-reference settings. Drives exact cross-file ``calls`` edges."""

    mode: Literal["auto", "on", "off"] = Field(
        default="auto",
        description=(
            "auto = enable an on-toggled language when its server binary is "
            "detected on PATH/venv; on = force on-toggled languages regardless "
            "of detection; off = disable LSP entirely."
        ),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _coerce_yaml_bool(cls, v: Any) -> Any:
        """YAML parses bare ``on``/``off`` as booleans — map them back."""
        if isinstance(v, bool):
            return _BOOL_TO_MODE[v]
        return v

    python: bool = Field(
        default=True,
        description="Consider Python for LSP (needs pyright when mode=auto).",
    )
    typescript: bool = Field(
        default=True,
        description=(
            "Consider TypeScript/JavaScript for LSP "
            "(needs typescript-language-server when mode=auto)."
        ),
    )


class GraphIndexingConfig(BaseModel):
    """Parsed ``graph_indexing:`` section."""

    lsp: GraphLspConfig = Field(default_factory=GraphLspConfig)


def load_graph_indexing_config(
    config_path: Path | None = None,
) -> GraphIndexingConfig:
    """Load ``graph_indexing:``, or defaults (auto) if the block is absent."""
    cfg = GraphIndexingConfig()
    try:
        raw = load_raw_config(config_path)
        block = raw.get("graph_indexing")
        if isinstance(block, dict):
            cfg = GraphIndexingConfig(
                **{
                    k: v
                    for k, v in block.items()
                    if k in GraphIndexingConfig.model_fields
                }
            )
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.debug("graph_indexing config load failed: %s", exc)
    return cfg
