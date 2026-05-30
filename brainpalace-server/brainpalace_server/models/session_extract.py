"""Phase 060 — strict models for a session extraction payload.

Mirrors the frozen 020-spike extraction schema. The LLM that produces this runs
inside the AI coding tool (070 manual command / 080 SessionEnd subagent); the
server only validates + persists it (no server-side LLM). ``extra="forbid"``
enforces the schema rule that there are no extra top-level keys, and the
relation vocabulary is closed so the phase-100 graph stays queryable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Closed relation vocabulary (020 schema §3). No free-text relations.
Relation = Literal[
    "touches",  # edit/create → file
    "fixed-by",  # error/bug → fix/commit/decision
    "superseded-by",  # decision_v1 → decision_v2
    "ran-in",  # tool/command → session
    "depends-on",  # phase/task → prerequisite
    "decided",  # session/actor → decision
]

FileAction = Literal["edit", "create", "read"]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="The decision, imperative/declarative.")
    rationale: str | None = Field(default=None, description="Why; null if unstated.")
    files: list[str] = Field(default_factory=list, description="Files concerned.")
    supersedes: str | None = Field(
        default=None, description="Text of a prior decision this replaces."
    )


class FileTouched(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    action: FileAction


class Triplet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    relation: Relation
    object: str
    evidence_turn: int | None = Field(
        default=None, description="Supporting turn index, null if diffuse."
    )


class SessionExtraction(BaseModel):
    """One extraction object per session (020 frozen schema)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_path: str | None = None
    branch: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    summary: str = Field(..., description="<= ~120 words; what was accomplished.")
    open_threads: list[str] = Field(default_factory=list)

    decisions: list[Decision] = Field(default_factory=list)
    files_touched: list[FileTouched] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    triplets: list[Triplet] = Field(default_factory=list)


class SessionExtractResult(BaseModel):
    """What the store operation persisted."""

    session_id: str
    summary_chunks: int = 0
    decision_chunks: int = 0
    triplets_stored: int = 0
    digest_updated: bool = False
