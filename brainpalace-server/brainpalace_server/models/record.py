"""Typed numeric records for the compute query class (Phase 1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from brainpalace_server.models.domains import DEFAULT_DOMAIN


class RecordCandidate(BaseModel):
    """Extractor output, before the server assigns id/provenance/confidence."""

    model_config = ConfigDict(extra="forbid")
    subject: str = Field(..., min_length=1)
    metric: str = Field(..., min_length=1)
    value: float
    unit: str | None = None
    ts: str | None = None  # ISO-8601; None if the source carries no timestamp


class Record(BaseModel):
    """A persisted, immutable measurement with provenance."""

    model_config = ConfigDict(frozen=True)
    id: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    metric: str = Field(..., min_length=1)
    value: float
    unit: str | None = None
    ts: str | None = None
    domain: str = DEFAULT_DOMAIN
    source: str | None = None
    source_id: str | None = None
    ingested_at: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    properties: dict[str, str] = Field(default_factory=dict)
