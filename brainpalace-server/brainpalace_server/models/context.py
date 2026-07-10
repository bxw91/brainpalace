"""Models for the session-start context block (Phase 035)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    """A frozen-snapshot context block assembled at session start."""

    text: str = Field(..., description="Rendered context block (markdown)")
    token_estimate: int = Field(default=0, description="Approx tokens (chars/4)")
    sections: list[str] = Field(
        default_factory=list,
        description="Slices actually included, e.g. ['project_facts', 'memory']",
    )
    truncated: bool = Field(
        default=False, description="True if some memories were dropped for budget"
    )
    memory_count: int = Field(default=0, description="Curated memories included")
    curate_due: bool = Field(
        default=False,
        description="True when an auto-curation nudge should fire this session",
    )
    blocked_job: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Summary of a budget-blocked indexing job (job_id, folder_path, "
            "estimated_tokens, limit, blocked_since), or null."
        ),
    )
