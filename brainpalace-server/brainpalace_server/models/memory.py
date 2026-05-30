"""Models for the curated memory namespace (Phase 030).

Curated, per-fact memory lives in a git-tracked markdown file (the source of
truth, ADR 0001) and is mirrored into a Chroma shadow collection. These models
describe a single memory entry and the request/response surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_SECTION = "Notes"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory(BaseModel):
    """A single curated memory entry (one markdown list item)."""

    id: str = Field(..., description="Stable id, e.g. mem_1a2b3c4d")
    text: str = Field(..., min_length=1, description="The fact, one line")
    section: str = Field(default=DEFAULT_SECTION, description="Markdown ## section")
    tags: list[str] = Field(default_factory=list)
    origin: str = Field(default="user", description="user | ai | promoted")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=_now_iso)
    last_referenced_at: str | None = Field(default=None)
    obsoleted_at: str | None = Field(default=None)
    superseded_by: str | None = Field(default=None)

    @property
    def is_active(self) -> bool:
        return self.obsoleted_at is None

    def to_metadata(self) -> dict[str, Any]:
        """Flat metadata for the Chroma shadow index (no None/list values)."""
        return {
            "memory_id": self.id,
            "section": self.section,
            "tags": ",".join(self.tags),
            "origin": self.origin,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "source_type": "memory",
        }


class MemoryCreate(BaseModel):
    """Request to create a memory."""

    text: str = Field(..., min_length=1, max_length=2000)
    section: str = Field(default=DEFAULT_SECTION)
    tags: list[str] = Field(default_factory=list)
    origin: str = Field(default="user")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryResponse(BaseModel):
    """A memory returned to a caller."""

    memory: Memory
    message: str = ""


class MemoryListResponse(BaseModel):
    memories: list[Memory] = Field(default_factory=list)
    total: int = 0
    char_count: int = Field(default=0, description="Current size of the markdown file")
    char_cap: int = Field(default=0, description="Configured cap")


class MemoryRecallRequest(BaseModel):
    """Recall against the memory namespace only (no code/docs)."""

    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


class MemoryHit(BaseModel):
    """A scored memory recall result."""

    id: str
    text: str
    score: float
    section: str = DEFAULT_SECTION
    tags: list[str] = Field(default_factory=list)


class MemoryRecallResponse(BaseModel):
    hits: list[MemoryHit] = Field(default_factory=list)
    total: int = 0
    query_time_ms: float = 0.0
