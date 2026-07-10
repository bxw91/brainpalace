"""Per-project identity config (config.yaml `project:` section).

``domain`` names this project's own knowledge domain (default ``"code"`` —
a BrainPalace project's primary purpose is indexing its own codebase).
``folders add --domain`` defaults to this value server-side when the caller
omits ``--domain``; an EXTERNAL folder that EXPLICITLY claims this same
domain is treated as an authoritative claim over the project's own identity
and requires ``--force`` (Phase 6.5 Task 5) — the same 403 gate that already
protects an explicit ``--authority authoritative`` claim (Task 2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    domain: str = Field(
        default="code",
        description=(
            "This project's own knowledge domain. New folders default their "
            "domain to this value when --domain is omitted; an external "
            "folder that EXPLICITLY claims this same domain is treated as "
            "an authoritative claim and requires --force."
        ),
    )
