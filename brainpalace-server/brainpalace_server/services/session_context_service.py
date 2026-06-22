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
from typing import TYPE_CHECKING

from brainpalace_server.config.settings import settings
from brainpalace_server.models.context import SessionContext

if TYPE_CHECKING:
    from brainpalace_server.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

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
        return SessionContext(
            text=text,
            token_estimate=_est_tokens(text),
            sections=sections,
            truncated=truncated,
            memory_count=memory_count,
        )
