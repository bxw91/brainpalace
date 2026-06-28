"""Request/response models for the extraction drain endpoints (Plan 3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class PendingItem(BaseModel):
    source: str  # "doc" | "session"
    id: str  # chunk_id (doc) or session_id (session)
    text: str | None = None  # doc chunk text (None for session)
    path: str | None = None  # session transcript path (None for doc)


class PendingBatch(BaseModel):
    items: list[PendingItem]
    doc_pending_total: int = 0  # full doc backlog count (for observability)


class TripletIn(BaseModel):
    subject: str
    predicate: str
    object: str
    subject_type: str | None = None
    object_type: str | None = None


class ExtractionSubmit(BaseModel):
    source: Literal["doc", "session"]
    chunk_id: str | None = None  # required when source == "doc"
    triplets: list[TripletIn] | None = None  # doc payload
    extraction: dict[str, Any] | None = (
        None  # session payload (validated as SessionExtraction)
    )


class SubmitResult(BaseModel):
    source: Literal["doc", "session"]
    id: str
    triplets_stored: int = 0
    marked_done: bool = False
