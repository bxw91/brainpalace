"""SourceAdapter contract + EmittedItem union + in-memory adapter registry.

NOTE: distinct from services/*ExtractionAdapter (graph-triplet extraction).
This is the ingestion seam: adapters emit typed items, ingestion/sink.py
enforces provenance/domain and routes by tier.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, Protocol, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict

from brainpalace_server.models.domains import register_domain
from brainpalace_server.models.record import RecordCandidate

IngestMode = Literal["eager", "lazy"]


class EmittedRecord(BaseModel):
    """Eager tier: promote to a typed Record now. id + confidence are
    adapter-owned (heterogeneous confidence rules); the sink assembles the
    final Record, computes salience, and stamps ingested_at."""

    model_config = ConfigDict(extra="forbid")
    candidate: RecordCandidate
    id: str
    domain: str
    source: str
    source_id: str
    confidence: float
    properties: dict[str, str] = {}
    mode: Literal["eager"] = "eager"


class EmittedReference(BaseModel):
    """Lazy tier: store a pointer + summary; fetch-and-extract on demand."""

    model_config = ConfigDict(extra="forbid")
    pointer: str
    summary: str
    domain: str
    source: str
    source_id: str
    mode: Literal["lazy"] = "lazy"


class EmittedDocument(BaseModel):
    """Documents tier — DECLARED, NOT routed in Phase 6 (no consumer)."""

    model_config = ConfigDict(extra="forbid")
    text: str
    metadata: dict[str, str] = {}
    domain: str
    source: str
    source_id: str
    # D6: optional per-item sensitivity override, forwarded to the
    # `IngestDoc` the sink constructs (additive; no existing emitter
    # affected — same precedent as `EmittedEntity.aliases`).
    sensitivity: str | None = None


class EmittedEntity(BaseModel):
    """Entities tier — DECLARED, NOT routed in Phase 6 (Phase 9).

    ``aliases`` and ``external_ref`` (G5 A4) let one emission assert
    "Ivan, also Ivo, matches voice-cluster-3" instead of three separate
    API calls once the identity store routes this tier: ``aliases``
    become ``upsert_alias`` calls, ``external_ref`` becomes an
    ``add_link(ref=..., ref_kind="external")``. Both are additive
    optionals — no existing emitter is affected."""

    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str
    domain: str
    source: str
    source_id: str
    aliases: list[str] = []
    external_ref: str | None = None


EmittedItem = Union[EmittedRecord, EmittedReference, EmittedDocument, EmittedEntity]


@runtime_checkable
class SourceAdapter(Protocol):
    domain: str
    source: str

    def emit(self, payload: Any) -> Iterable[EmittedItem]: ...


_ADAPTERS: list[SourceAdapter] = []


def register_adapter(a: SourceAdapter) -> None:
    register_domain(a.domain)
    _ADAPTERS.append(a)


def known_adapters() -> tuple[SourceAdapter, ...]:
    return tuple(_ADAPTERS)


def reset_adapters() -> None:
    """Test hook — the registry is in-memory (adapters re-register at startup)."""
    _ADAPTERS.clear()
