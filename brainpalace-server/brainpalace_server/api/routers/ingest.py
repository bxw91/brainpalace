"""Text-ingest API (spec Item 3 / G2): programmatic free-text ingest with
caller-supplied provenance. Synchronous — the token-budget guard rejects
oversized batches; the async job queue stays reserved for folder indexing."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brainpalace_server.models.domains import register_domain
from brainpalace_server.services.document_ingest_service import IngestDoc

logger = logging.getLogger(__name__)

router = APIRouter()


class IngestTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[IngestDoc]
    sensitivity: str = "normal"
    language: str | None = None


class RecordIngestItem(BaseModel):
    """One caller-asserted measurement. Mirrors ``RecordCandidate`` +
    provenance; ``confidence`` defaults to 1.0 (a first-party HTTP assertion
    is authoritative, like ingested documents) and the record id is derived
    server-side from provenance + the measurement, so re-ingest by
    ``source_id`` replaces cleanly."""

    model_config = ConfigDict(extra="forbid")
    subject: str = Field(..., min_length=1)
    metric: str = Field(..., min_length=1)
    value: float
    unit: str | None = None
    ts: str | None = None
    domain: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    properties: dict[str, str] = {}


class IngestRecordsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RecordIngestItem]
    sensitivity: str = "normal"


class ReferenceIngestItem(BaseModel):
    """One lazy-tier pointer + summary. The reference id is derived by the
    store from ``(source, pointer)``."""

    model_config = ConfigDict(extra="forbid")
    pointer: str = Field(..., min_length=1)
    summary: str = ""
    domain: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)


class IngestReferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReferenceIngestItem]
    sensitivity: str = "normal"


def _get_service(request: Request) -> Any:
    svc = getattr(request.app.state, "document_ingest_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail="Text ingest is not available (no embedding provider "
            "configured?). Check the server logs — a missing provider key "
            "(e.g. OPENAI_API_KEY) is named there.",
        )
    return svc


def _require_record_store(request: Request) -> Any:
    rs = getattr(request.app.state, "record_store", None)
    if rs is None:
        raise HTTPException(
            status_code=503, detail="RecordStore is not available on this server."
        )
    return rs


def _require_reference_store(request: Request) -> Any:
    store = getattr(request.app.state, "reference_catalog_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Reference catalog is not available on this server.",
        )
    return store


def _record_id(item: RecordIngestItem) -> str:
    """Deterministic id from provenance + the measurement — stable per source
    so a re-ingest of the same source_id replaces its rows (the store's
    ``replace_source`` deletes-then-inserts by source_id)."""
    parts = (
        item.domain,
        item.source,
        item.source_id,
        item.subject,
        item.metric,
        "" if item.ts is None else item.ts,
        repr(item.value),
    )
    return "rec_" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


@router.post(
    "/text",
    summary="Ingest free text with caller-supplied provenance",
    description=(
        "Chunks, embeds and indexes each item under its domain/source/"
        "source_id provenance. Re-ingesting a source_id replaces its chunks "
        "(unchanged text is not re-embedded). Results appear in bm25/vector/"
        "hybrid queries with source `ingest://<domain>/<source>/<source_id>`."
    ),
)
async def ingest_text(body: IngestTextRequest, request: Request) -> dict[str, Any]:
    svc = _get_service(request)
    for item in body.items:
        register_domain(item.domain)  # open registry; HTTP caller has no other channel
    try:
        result: dict[str, Any] = await svc.ingest_documents(
            body.items, sensitivity=body.sensitivity, language=body.language
        )
        await _invalidate_query_cache(request)
        return result
    except ValueError as exc:  # reserved-metadata collision etc.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        from brainpalace_server.providers.exceptions import ProviderError
        from brainpalace_server.services.indexing_service import BudgetExceededError

        if isinstance(exc, BudgetExceededError):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        if isinstance(exc, ProviderError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise


@router.post(
    "/records",
    summary="Ingest caller-asserted typed records (eager tier)",
    description=(
        "Persists each item as a typed Record under its domain/source/"
        "source_id provenance, replacing any existing records for that "
        "source_id. Routes through the shared write choke point (salience + "
        "ingested_at are stamped there). Works without an embedding provider."
    ),
)
async def ingest_records(
    body: IngestRecordsRequest, request: Request
) -> dict[str, Any]:
    from brainpalace_server.ingestion.adapter import EmittedRecord
    from brainpalace_server.ingestion.sink import (
        ProvenanceError,
        aingest,
        items_adapter,
    )
    from brainpalace_server.models.record import RecordCandidate

    record_store = _require_record_store(request)
    reference_store = getattr(request.app.state, "reference_catalog_store", None)

    emitted: list[Any] = []
    for item in body.items:
        register_domain(item.domain)  # open registry; HTTP caller has no other channel
        emitted.append(
            EmittedRecord(
                candidate=RecordCandidate(
                    subject=item.subject,
                    metric=item.metric,
                    value=item.value,
                    unit=item.unit,
                    ts=item.ts,
                ),
                id=_record_id(item),
                domain=item.domain,
                source=item.source,
                source_id=item.source_id,
                confidence=item.confidence,
                properties=item.properties,
            )
        )

    stamp = datetime.now(timezone.utc).isoformat()
    try:
        result = await aingest(
            items_adapter(emitted),
            None,
            record_store=record_store,
            reference_store=reference_store,
            ingested_at=stamp,
            sensitivity=body.sensitivity,
        )
    except ProvenanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _invalidate_query_cache(request)
    return {"records": result["records"]}


@router.post(
    "/references",
    summary="Ingest lazy-tier references (pointer + summary)",
    description=(
        "Persists each pointer + summary under its provenance, replacing any "
        "existing references for that source_id. Summaries are embedded at "
        "write time when an embedding provider is configured; otherwise they "
        "land unembedded and `POST /references/embed-missing` backfills them."
    ),
)
async def ingest_references(
    body: IngestReferencesRequest, request: Request
) -> dict[str, Any]:
    from brainpalace_server.ingestion.adapter import EmittedReference
    from brainpalace_server.ingestion.sink import (
        ProvenanceError,
        aingest,
        items_adapter,
    )

    reference_store = _require_reference_store(request)
    record_store = getattr(request.app.state, "record_store", None)
    # D3: keyless server → no document_ingest_service → no embedder → references
    # land unembedded (backfillable). Only embed when a provider is actually up.
    svc = getattr(request.app.state, "document_ingest_service", None)
    reference_embedder = getattr(svc, "embedding_generator", None)

    emitted: list[Any] = []
    for item in body.items:
        register_domain(item.domain)  # open registry; HTTP caller has no other channel
        emitted.append(
            EmittedReference(
                pointer=item.pointer,
                summary=item.summary,
                domain=item.domain,
                source=item.source,
                source_id=item.source_id,
            )
        )

    stamp = datetime.now(timezone.utc).isoformat()
    try:
        result = await aingest(
            items_adapter(emitted),
            None,
            record_store=record_store,
            reference_store=reference_store,
            reference_embedder=reference_embedder,
            ingested_at=stamp,
            sensitivity=body.sensitivity,
        )
    except ProvenanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _invalidate_query_cache(request)
    return {"references": result["references"]}


@router.get(
    "/sources",
    summary="List distinct ingested source_ids with provenance + chunk counts",
    description=(
        "Enumerates ingested documents grouped by source_id, reporting domain, "
        "source, chunk_count and ingested_at. Filter with `domain=` / `source=`. "
        "Non-`normal` chunks are hidden unless `include_sensitive=true` (a source "
        "with only sensitive chunks disappears from the default listing). An empty "
        "index returns an empty list, not a 404."
    ),
)
async def list_ingested_sources(
    request: Request,
    domain: str | None = None,
    source: str | None = None,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    svc = _get_service(request)
    sources = await svc.list_sources(
        domain=domain, source=source, include_sensitive=include_sensitive
    )
    return {"sources": sources, "total": len(sources)}


@router.get(
    "/text/{source_id}",
    summary="List one source_id's ingested chunks (paginated)",
    description=(
        "Returns the chunks (chunk_id, text, metadata) ingested under source_id, "
        "ordered by chunk_index and paginated via `offset`/`limit`. Non-`normal` "
        "chunks are hidden unless `include_sensitive=true`. An unknown source_id "
        "returns an empty chunk list (total 0), not a 404."
    ),
)
async def get_ingested_source_chunks(
    source_id: str,
    request: Request,
    offset: int = 0,
    limit: int = 50,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    svc = _get_service(request)
    result: dict[str, Any] = await svc.get_source_chunks(
        source_id,
        offset=max(offset, 0),
        limit=max(limit, 0),
        include_sensitive=include_sensitive,
    )
    return result


async def _invalidate_query_cache(request: Request) -> None:
    """Best-effort: bump the query-cache generation so a deleted source_id
    stops being served from a cached hit taken before the delete. Mirrors the
    invalidation the job worker does on reindex (query_cache.py);
    ``request.app.state.query_cache`` is absent in unit tests that build a
    bare ``FastAPI()`` around this router — treated as a no-op there."""
    query_cache = getattr(request.app.state, "query_cache", None)
    if query_cache is not None:
        await query_cache.invalidate_all()


@router.delete(
    "/text/{source_id}",
    summary="Delete all ingested chunks for a source_id (un-ingest)",
)
async def delete_ingested(source_id: str, request: Request) -> dict[str, Any]:
    svc = _get_service(request)
    result: dict[str, Any] = await svc.delete_source(source_id)
    await _invalidate_query_cache(request)
    return result


@router.delete(
    "/source/{source_id}",
    summary="Full forget: delete a source_id across all three ingest tiers",
    description=(
        "Cascades a delete across document chunks (identity links included, "
        "via `DocumentIngestService.delete_source`), typed records, and "
        "lazy-tier references for the given source_id, returning per-tier "
        "counts. `DELETE /ingest/text/{source_id}` keeps its narrower, "
        "published chunks-only meaning — use this endpoint for a full forget."
    ),
)
async def forget_ingested_source(source_id: str, request: Request) -> dict[str, Any]:
    from brainpalace_server.services.document_ingest_service import forget_source

    svc = getattr(request.app.state, "document_ingest_service", None)
    record_store = getattr(request.app.state, "record_store", None)
    reference_store = getattr(request.app.state, "reference_catalog_store", None)
    if svc is None and record_store is None and reference_store is None:
        raise HTTPException(
            status_code=503, detail="No ingest stores are available on this server."
        )
    result: dict[str, Any] = await forget_source(
        source_id,
        document_ingest_service=svc,
        record_store=record_store,
        reference_store=reference_store,
    )
    await _invalidate_query_cache(request)
    return result
