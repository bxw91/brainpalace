"""Shared extraction-engine config (Plan 4). One section selects the LLM engine
for BOTH doc-graph triplets and session distillation; code default ``off`` is the
cost-safety lock (spec §4/§10). ``extraction.mode`` is the sole engine selector
for both consumers — the legacy ``session_extraction.mode`` field is removed."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import load_raw_config
from brainpalace_server.config.session_config import (
    ExtractMode,
    _env_flag,
)

logger = logging.getLogger(__name__)


class ExtractionConfig(BaseModel):
    mode: ExtractMode = Field(
        default="off",
        description="off (default, cost-safe) | subagent | auto | provider — "
        "engine for docs + sessions.",
    )
    grace_hours: int = Field(
        default=24,
        ge=0,
        description="auto mode: hours the free subagent gets before the paid "
        "provider drains a doc chunk.",
    )
    drain_batch_size: int = Field(
        default=8,
        ge=1,
        description="max items drained per reconcile tick (shared throttle).",
    )
    drain_cooldown_seconds: int = Field(
        default=300,
        ge=0,
        description="min seconds between drain ticks (shared cooldown).",
    )
    drain_doc_max_per_turn: int = Field(
        default=4,
        ge=0,
        description="max doc chunk ids routed to graph-triplet-extractor per "
        "user-prompt turn (burst cap; 0 = unlimited).",
    )
    drain_session_max_per_turn: int = Field(
        default=2,
        ge=0,
        description="max session ids routed to chat-session-extractor per "
        "user-prompt turn (burst cap; 0 = unlimited).",
    )
    max_provider_items_per_hour: int = Field(
        default=60,
        ge=0,
        description="rolling-hour ceiling on paid-provider extraction calls "
        "(billable providers only; 0 = unlimited). Stops the reconciler tick "
        "when reached; items stay pending.",
    )
    provider_session_max_chunks: int = Field(
        default=6,
        ge=0,
        description="max LLM calls per session during provider distillation "
        "(billable providers only; 0 = unlimited). Oversized transcripts are "
        "truncated beyond this many chunks.",
    )
    provider_context_tokens: int = Field(
        default=0,
        ge=0,
        description="summarization model context window in tokens, used to "
        "derive a safe chunk size. 0 = use the model→window map (or the safe "
        "floor for unknown models). Prefilled automatically on model selection; "
        "edit to override.",
    )
    distill_chunk_chars: int = Field(
        default=0,
        ge=0,
        description="explicit char budget per distillation call (overrides the "
        "window-derived size when > 0). 0 = derive from provider_context_tokens "
        "or the model→window map.",
    )
    max_pending: int = Field(
        default=50000,
        ge=0,
        description="high-water mark for the doc extraction queue. When "
        "count_pending() >= max_pending, headless indexing producers (file-watcher, "
        "job-worker) pause scheduling new files until the queue drains below 80%%. "
        "0 = disabled (never pause).",
    )


def _coerce_mode(v: Any) -> ExtractMode:
    if v is False:  # YAML 1.1: bare `off` → boolean False
        return "off"
    return v if v in ("auto", "subagent", "provider", "off") else "off"


def load_extraction_config(config_path: Path | None = None) -> ExtractionConfig:
    block: dict[str, Any] | None = None
    try:
        raw = load_raw_config(config_path)
        if isinstance(raw.get("extraction"), dict):
            block = raw["extraction"]
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("Could not parse extraction config: %s", exc)
    if not block:
        return ExtractionConfig()
    fields = {k: v for k, v in block.items() if k in ExtractionConfig.model_fields}
    if "mode" in fields:
        fields["mode"] = _coerce_mode(fields["mode"])
    try:
        return ExtractionConfig(**fields)
    except ValueError as exc:
        logger.warning("Invalid extraction block, using defaults: %s", exc)
        return ExtractionConfig()


def resolve_extraction_mode(
    consumer: Literal["doc", "session"], config_path: Path | None = None
) -> ExtractMode:
    """``extraction.mode`` governs both consumers (doc-graph + session). Absent it,
    both default to ``off`` (cost-safe). There is no per-consumer legacy fallback."""
    try:
        raw = load_raw_config(config_path)
        ext = raw.get("extraction") if isinstance(raw, dict) else None
    except (OSError, yaml.YAMLError, ValueError):
        ext = None
    if isinstance(ext, dict) and "mode" in ext:
        return _coerce_mode(ext["mode"])
    return "off"


def extraction_provider_enabled() -> bool:
    """Second cost lock for the PAID provider executor (both consumers). New
    canonical env; legacy SESSION_DISTILL_ENABLED kept as back-compat (H2)."""
    return _env_flag("EXTRACTION_PROVIDER_ENABLED", default=False) or _env_flag(
        "SESSION_DISTILL_ENABLED", default=False
    )
