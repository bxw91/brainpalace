"""Phase 050 — per-project ``session_indexing:`` config.

Two **independent** capabilities live under this block, each gated by the
presence of its config and an env kill-switch:

- **archive** — copy raw transcripts into ``.brainpalace/`` (durable backup, no
  embeddings). Default ON, including for *existing* projects whose config
  predates this block (absent-block fallback). Kill-switch:
  ``SESSION_ARCHIVE_ENABLED=false``.
- **index** — embed archived transcripts into the vector store (billable
  opt-in). Default ON only when the ``session_indexing`` block is present
  (i.e. ``brainpalace init`` wrote it); absent block ⇒ index OFF. Kill-switch:
  ``SESSION_INDEXING_ENABLED=false``.

Net: absent block ⇒ archive ON, index OFF. Present block ⇒ both default ON,
each overridable.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file

logger = logging.getLogger(__name__)

#: Tool slug stamped onto archive folder names + manifest entries. Only Claude
#: Code is supported today; future tools (codex, gemini, opencode) extend this.
DEFAULT_TOOL = "claude-code"


class SessionArchiveConfig(BaseModel):
    """Raw-transcript archive settings (durable, user-curatable copies).

    An **independent** switch (not sub-gated by the parent ``enabled``): archive
    runs whenever this is on, even when indexing is off. Default on.
    """

    enabled: bool = Field(
        default=True,
        description="Copy raw transcripts under .brainpalace/ (no embeddings).",
    )
    dir: str = Field(
        default=".brainpalace/session_archive",
        description="Archive directory (relative to project root or absolute).",
    )
    retain_days: int = Field(
        default=0,
        description="Archive age cutoff in days; <=0 means keep forever.",
    )


class SessionIndexingConfig(BaseModel):
    """Parsed ``session_indexing:`` section.

    Field defaults model a *present* block (both capabilities ON). The
    absent-block case (archive ON, index OFF) is applied in
    :func:`load_session_indexing_config` / :func:`resolve_session_capabilities`.
    """

    enabled: bool = Field(
        default=True, description="INDEX: embed session transcripts (opt-in cost)."
    )
    include_user_turns: bool = Field(
        default=False,
        description="Index human user dialogue too (default: assistant/tools only).",
    )
    retain_days: int = Field(
        default=0,
        description="Index age cutoff in days; <=0 means forever (no cutoff).",
    )
    window: int = Field(default=4, description="Turns per sliding window (3-5).")
    stride: int = Field(default=2, description="Window stride in turns.")
    watch_debounce_ms: int = Field(
        default=30000,
        description="Debounce (ms) for the live session watcher. Sessions are "
        "bursty (per-message writes); batching a whole turn avoids "
        "redundant re-index passes. Freshness is low-value here "
        "(recall targets past sessions).",
    )
    sessions_dir: str | None = Field(
        default=None,
        description="Override the auto-resolved runtime session directory.",
    )
    archive: SessionArchiveConfig = Field(default_factory=SessionArchiveConfig)


#: Distillation engine: auto (decide by plugin presence at runtime) | subagent
#: (Claude Code plugin) | provider (server LLM) | off. See ``session_extraction:``
#: in config.yaml.
ExtractMode = Literal["auto", "subagent", "provider", "off"]


class SessionExtractionConfig(BaseModel):
    """Parsed ``session_extraction:`` block — selects the distillation engine.

    Authoritative engine selector. ``init`` writes ``subagent``: session
    summarization happens ONLY inside Claude Code (the plugin's subagent, free on
    your Claude Code subscription). The server never falls back to a paid
    provider on its own — if Claude Code did not summarize a session, it simply
    stays un-summarized. ``--no-extract`` ⇒ ``off``. Absent block ⇒ default
    ``subagent``. ``provider`` (server-side LLM distillation, possibly metered)
    and ``auto`` (subagent with a 24h provider safety net) remain available only
    as explicit opt-in.
    """

    mode: ExtractMode = Field(
        default="subagent",
        description="subagent (plugin-only, default) | auto | provider | off.",
    )


def load_session_extraction_config(
    config_path: Path | None = None,
) -> SessionExtractionConfig:
    """Load the ``session_extraction:`` block; default ``subagent`` if absent.

    Precedence: the project ``.brainpalace/config.yaml`` (resolved by
    :func:`_find_config_file`, which walks up from CWD) wins over the global XDG
    config. An invalid/malformed block falls back to the ``subagent`` default
    rather than raising — a config typo must never silently switch on paid
    server-side distillation.
    """
    path = config_path or _find_config_file()
    block: dict[str, Any] | None = None
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            maybe = raw.get("session_extraction")
            if isinstance(maybe, dict):
                block = maybe
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("Could not parse session_extraction config: %s", exc)

    if block is None:
        return SessionExtractionConfig()
    fields = {
        k: v for k, v in block.items() if k in SessionExtractionConfig.model_fields
    }
    # YAML 1.1 parses an unquoted ``off`` as the boolean False — restore the
    # intended "off" string so hand-written `mode: off` works without quotes.
    if fields.get("mode") is False:
        fields["mode"] = "off"
    try:
        return SessionExtractionConfig(**fields)
    except ValueError as exc:
        logger.warning("Invalid session_extraction block, using subagent: %s", exc)
        return SessionExtractionConfig()


@dataclass(frozen=True)
class SessionCapabilities:
    """Resolved on/off state for the two independent session capabilities."""

    archive_enabled: bool
    index_enabled: bool
    tool: str = DEFAULT_TOOL


def _env_flag(name: str, *, default: bool = True) -> bool:
    """Generic env switch. Absent ⇒ ``default`` (config then decides)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_master_enabled() -> bool:
    """``SESSION_INDEXING_ENABLED`` master switch for the INDEX capability."""
    return _env_flag("SESSION_INDEXING_ENABLED")


def _env_archive_enabled() -> bool:
    """``SESSION_ARCHIVE_ENABLED`` master switch for the ARCHIVE capability."""
    return _env_flag("SESSION_ARCHIVE_ENABLED")


def session_distill_enabled() -> bool:
    """``SESSION_DISTILL_ENABLED`` switch for the PROVIDER distiller.

    **Disabled by default** (absent ⇒ ``False``): the server-side provider
    distiller — the only billable summarization path — never runs unless you
    explicitly set ``SESSION_DISTILL_ENABLED`` truthy (``1``/``true``/``yes``/
    ``on``). This is a hard, mode-independent lock: it keeps even an explicit
    ``mode: provider``/``auto`` (incl. legacy configs) from billing until you opt
    in. Summarization then stays inside Claude Code (``mode: subagent``).
    """
    return _env_flag("SESSION_DISTILL_ENABLED", default=False)


def session_distill_grace_hours() -> float:
    """Hours a session must be un-marked before the provider safety net distils it
    in ``auto`` mode even when the plugin appears installed (covers a disabled or
    never-reopened plugin). Default 24."""
    raw = os.getenv("SESSION_DISTILL_GRACE_HOURS")
    try:
        return float(raw) if raw is not None else 24.0
    except ValueError:
        return 24.0


def retain_cutoff(retain_days: int, now: float | None = None) -> float | None:
    """Epoch-seconds cutoff for a ``retain_days`` window.

    Returns ``None`` (keep forever / no cutoff) when ``retain_days <= 0``,
    otherwise ``now - retain_days * 86400``. Files older than the cutoff are
    skipped; ``None`` means never skip.
    """
    if retain_days <= 0:
        return None
    now = time.time() if now is None else now
    return now - retain_days * 86400


def load_session_indexing_config(
    config_path: Path | None = None,
) -> SessionIndexingConfig:
    """Load the ``session_indexing:`` block.

    - **Block present:** parse it; omitted keys take the (ON) field defaults.
    - **Block absent** (no file, or file without the block): index is OFF
      (``enabled=False``) but archive stays ON (its field default).

    ``SESSION_INDEXING_ENABLED=false`` forces ``enabled`` off regardless.
    Archive's env switch is applied in :func:`resolve_session_capabilities`.
    """
    path = config_path or _find_config_file()
    block: dict[str, Any] | None = None
    if path and Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text()) or {}
            maybe = raw.get("session_indexing")
            if isinstance(maybe, dict):
                block = maybe
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("Could not parse session_indexing config: %s", exc)

    if block is not None:
        try:
            cfg = SessionIndexingConfig(
                **{
                    k: v
                    for k, v in block.items()
                    if k in SessionIndexingConfig.model_fields
                }
            )
        except ValueError as exc:
            logger.warning("Invalid session_indexing block, using defaults: %s", exc)
            cfg = SessionIndexingConfig()
    else:
        # Absent block: index OFF, archive ON (its default).
        cfg = SessionIndexingConfig(enabled=False)

    if not _env_master_enabled():
        cfg = cfg.model_copy(update={"enabled": False})
    return cfg


def resolve_session_capabilities(
    cfg: SessionIndexingConfig,
    tool: str = DEFAULT_TOOL,
) -> SessionCapabilities:
    """Single source of truth for the archive/index on-off decision.

    ``cfg`` must come from :func:`load_session_indexing_config` (which already
    encodes absent-block ⇒ index OFF and the ``SESSION_INDEXING_ENABLED``
    master switch). This layer applies the ``SESSION_ARCHIVE_ENABLED`` switch.
    """
    return SessionCapabilities(
        archive_enabled=bool(cfg.archive.enabled) and _env_archive_enabled(),
        index_enabled=bool(cfg.enabled),
        tool=tool,
    )
