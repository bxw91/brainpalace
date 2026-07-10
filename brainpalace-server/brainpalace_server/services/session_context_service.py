"""Session-start context assembler (Phase 035 — memory-injection).

Builds a compact, budget-capped "frozen snapshot" the AI loads once at session
start so it begins already knowing the project's durable facts — the proactive
*push* complementing 030's query-time *boost*.

Slices, in priority order:
  1. **project facts** — root, branch, indexed doc count (always present, tiny).
  2. **curated memory** — active entries from 030, highest-confidence /
     most-recent first, added until the token budget is hit.
  3. **last-session summary** — PLACEHOLDER until Phase 050 (session-ingest)
     exists; absent from ``sections`` until then.

Budget is a directional char estimate (``tokens ≈ chars / 4``); the block is
small and the cap generous. Loaded once per session (mid-session memory writes
take effect next session — prefix-cache friendly).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brainpalace_server.config.extraction_config import resolve_extraction_mode
from brainpalace_server.config.settings import settings
from brainpalace_server.models.context import SessionContext
from brainpalace_server.storage_paths import STATE_SUBDIR

if TYPE_CHECKING:
    from brainpalace_server.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


def curate_due(state_dir: Path, memory_count: int) -> bool:
    """True when an in-session auto-curation nudge should fire: session extraction is
    running in an in-session mode (subagent/auto), memory is non-empty, and the weekly
    stamp is stale/absent. PURE — reads the stamp, never writes it (the CLI stamps
    `last-curate` on emit; the provider curator stamps itself server-side).

    `provider`/`off` return False here: provider curation is the server's job (see
    MemoryCurator), off means no curation at all."""
    if memory_count <= 0:
        return False
    if resolve_extraction_mode("session") not in ("subagent", "auto"):
        return False
    stamp = state_dir / STATE_SUBDIR / "last-curate"
    interval = getattr(settings, "MEMORY_CURATE_INTERVAL_DAYS", 7) * 86400
    try:
        if stamp.exists() and time.time() - stamp.stat().st_mtime < interval:
            return False
    except Exception:  # noqa: BLE001 — unreadable stamp → fail closed (no nudge)
        return False
    return True


_CHARS_PER_TOKEN = 4


def _est_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


class SessionContextService:
    """Assembles the session-start context block."""

    def __init__(
        self,
        memory_service: MemoryService | None = None,
        budget_tokens: int | None = None,
    ) -> None:
        self._memory = memory_service
        self.budget_tokens = (
            budget_tokens
            if budget_tokens is not None
            else settings.CONTEXT_BUDGET_TOKENS
        )

    def build(
        self,
        project_root: str | None = None,
        branch: str | None = None,
        doc_count: int | None = None,
        blocked_job: dict[str, Any] | None = None,
    ) -> SessionContext:
        sections: list[str] = []
        lines: list[str] = ["# BrainPalace — session context", ""]

        # 1. Project facts (always present)
        facts = ["## Project"]
        if project_root:
            facts.append(f"- root: {project_root}")
        if branch:
            facts.append(f"- branch: {branch}")
        if doc_count is not None:
            facts.append(f"- indexed chunks: {doc_count}")
        if blocked_job:
            tokens = blocked_job.get("estimated_tokens")
            limit = blocked_job.get("limit")
            facts.append(
                f"- WARNING: indexing paused — job {blocked_job.get('job_id')} needs "
                f"~{tokens:,} embedding tokens (cap {limit:,}). Approve: "
                f"brainpalace jobs {blocked_job.get('job_id')} --approve"
                if isinstance(tokens, int) and isinstance(limit, int)
                else f"- WARNING: indexing paused — job {blocked_job.get('job_id')}. "
                f"Approve: brainpalace jobs {blocked_job.get('job_id')} --approve"
            )
        if len(facts) > 1:
            lines.extend(facts)
            lines.append("")
            sections.append("project_facts")

        budget_chars = self.budget_tokens * _CHARS_PER_TOKEN
        truncated = False

        # Live recall flags — gate what session-derived data we surface.
        from brainpalace_server.config.session_config import session_recall_flags

        vector_on, summarization_on = session_recall_flags()

        # 2. Curated memory (priority: confidence desc, then most-recent)
        memories = []
        if self._memory is not None:
            try:
                memories = [m for m in self._memory.load() if m.is_active]
            except Exception as exc:  # noqa: BLE001 — context must never fail hard
                logger.warning("session context: memory load failed: %s", exc)
                memories = []
        # Hard-off session recall: when summarization is disabled, drop
        # auto-promoted session-derived memory (origin != "user"); keep only
        # manually-saved `brainpalace remember` facts.
        if not summarization_on:
            memories = [m for m in memories if (m.origin or "user") == "user"]
        # Default-deny sensitive memory on the session-start PUSH surface: this
        # block feeds the SessionStart hook / MCP context resource / dashboard,
        # none of which can opt in. Missing mark ⇒ "normal" ⇒ visible.
        memories = [
            m for m in memories if getattr(m, "sensitivity", "normal") == "normal"
        ]
        memories.sort(key=lambda m: (m.confidence, m.created_at), reverse=True)

        if memories:
            mem_lines = ["## Curated memory"]
            included = 0
            for m in memories:
                entry = f"- ({m.section}) {m.text}"
                projected = "\n".join(lines + mem_lines + [entry, ""])
                if len(projected) > budget_chars and included > 0:
                    truncated = True
                    break
                mem_lines.append(entry)
                included += 1
            if included > 0:
                lines.extend(mem_lines)
                lines.append("")
                sections.append("memory")

        # 3. Conditional session-recall instruction. Tell the agent that prior
        # sessions are searchable ONLY when a producing feature is live — never
        # point it at a disabled (and possibly stale) source. Both off ⇒ no line.
        if vector_on or summarization_on:
            recall_what = (
                "prior decisions & past sessions"
                if vector_on and summarization_on
                else "past sessions" if vector_on else "prior decisions"
            )
            lines.append("## Session recall")
            lines.append(
                f"- {recall_what} are searchable: `brainpalace query "
                '"..." --mode multi` (or `recall` for curated memory).'
            )
            lines.append("")
            sections.append("session_recall")

        # 4. last-session summary — PLACEHOLDER (Phase 050). Intentionally absent.

        text = "\n".join(lines).rstrip() + "\n"
        memory_count = sum(1 for line in lines if line.startswith("- ("))

        curate_flag = False
        if project_root and self._memory is not None:
            try:
                active_total = sum(1 for m in self._memory.load() if m.is_active)
                curate_flag = curate_due(
                    Path(project_root) / ".brainpalace", active_total
                )
            except Exception as exc:  # noqa: BLE001 — gate must never fail the block
                logger.warning("session context: curate gate failed: %s", exc)

        return SessionContext(
            text=text,
            token_estimate=_est_tokens(text),
            sections=sections,
            truncated=truncated,
            memory_count=memory_count,
            curate_due=curate_flag,
            blocked_job=blocked_job,
        )
