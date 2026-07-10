"""The single ingest choke point (C5): validates domain-registration + full
provenance on every emitted item, then routes by tier. eager -> RecordStore,
lazy -> ReferenceCatalogStore. document/entity are declared-not-routed
(Phase 9 / first document adapter). ingested_at is stamped here (single
clock); salience is computed here."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from brainpalace_server.indexing.salience import score_salience
from brainpalace_server.ingestion.adapter import (
    EmittedDocument,
    EmittedEntity,
    EmittedRecord,
    EmittedReference,
    SourceAdapter,
)
from brainpalace_server.models.domains import is_known_domain
from brainpalace_server.models.record import Record
from brainpalace_server.storage.identity_store import Alias, Link, Person
from brainpalace_server.storage.reference_catalog_store import ReferenceEntry, ref_id


class ProvenanceError(ValueError):
    """An emitted item is missing provenance or names an unregistered domain."""


@dataclass
class _SummaryPiece:
    """A reference summary wrapped in the `.text`-bearing shape the
    embed_chunks protocol expects (mirrors DocumentIngestService's
    `_Piece`) — one embedder interface serves both documents and
    reference summaries."""

    text: str


@dataclass
class _ItemsAdapter:
    """One-shot ``SourceAdapter`` over a pre-built list of ``EmittedItem``s.

    The HTTP write path (``POST /ingest/records`` / ``/ingest/references``, D1)
    builds typed items in the router, then feeds them through ``aingest`` via
    this adapter so the single write choke point (C5) still validates
    provenance, computes salience, stamps ``ingested_at`` and embeds reference
    summaries — none of it re-implemented in the router. ``domain``/``source``
    only satisfy the ``SourceAdapter`` protocol; ``aingest`` reads provenance
    off each emitted item, never off the adapter."""

    domain: str
    source: str
    items: list[Any]

    def emit(self, payload: Any) -> list[Any]:
        return list(self.items)


def items_adapter(items: list[Any]) -> _ItemsAdapter:
    """Wrap already-built emitted items as a one-shot adapter for ``aingest``.

    Added HERE (not in the router) per plan A5 so the sink stays the only
    place that knows the adapter shape."""
    first = items[0] if items else None
    return _ItemsAdapter(
        domain=getattr(first, "domain", "") or "",
        source=getattr(first, "source", "") or "",
        items=list(items),
    )


def _check_provenance(item: Any) -> None:
    domain = getattr(item, "domain", None)
    source = getattr(item, "source", None)
    source_id = getattr(item, "source_id", None)
    if not domain or not source or not source_id:
        raise ProvenanceError(
            f"emitted item missing provenance (domain/source/source_id): {item!r}"
        )
    if not is_known_domain(domain):
        raise ProvenanceError(f"unregistered domain: {domain!r}")


def _route_record_or_reference(
    item: Any,
    records_by_source: dict[str, list[Record]],
    refs_by_source: dict[str, list[ReferenceEntry]],
    ingested_at: str,
    sensitivity: str,
) -> None:
    """Route one eager/lazy item into the accumulators. Shared verbatim by
    ``ingest`` and ``aingest`` so the record/reference behavior cannot drift.

    Raises ``ProvenanceError`` for an unknown item type. Document/entity tiers
    are NOT handled here — each caller decides their fate before delegating."""
    if isinstance(item, EmittedRecord):
        c = item.candidate
        rec = Record(
            id=item.id,
            subject=c.subject,
            metric=c.metric,
            value=c.value,
            unit=c.unit,
            ts=c.ts,
            domain=item.domain,
            source=item.source,
            source_id=item.source_id,
            ingested_at=ingested_at,
            confidence=item.confidence,
            properties=item.properties,
            sensitivity=sensitivity,
        )
        rec = rec.model_copy(update={"salience": score_salience(rec)})
        records_by_source[item.source_id].append(rec)
    elif isinstance(item, EmittedReference):
        refs_by_source[item.source_id].append(
            ReferenceEntry(
                id=ref_id(item.pointer, item.source),
                domain=item.domain,
                source=item.source,
                source_id=item.source_id,
                pointer=item.pointer,
                summary=item.summary,
                ingested_at=ingested_at,
                sensitivity=sensitivity,
            )
        )
    else:  # pragma: no cover - union is exhaustive
        raise ProvenanceError(f"unknown emitted item type: {type(item)!r}")


def _persist_records_and_refs(
    records_by_source: dict[str, list[Record]],
    refs_by_source: dict[str, list[ReferenceEntry]],
    record_store: Any,
    reference_store: Any,
) -> tuple[int, int]:
    """Replace-source persistence for the accumulated records/refs. Shared
    verbatim by ``ingest`` and ``aingest``."""
    n_rec = 0
    for source_id, recs in records_by_source.items():
        n_rec += record_store.replace_source(source_id, recs)

    n_ref = 0
    if refs_by_source:
        if reference_store is None:
            raise ProvenanceError("lazy items emitted but no reference_store bound")
        for source_id, refs in refs_by_source.items():
            n_ref += reference_store.replace_source(source_id, refs)

    return n_rec, n_ref


def ingest(
    adapter: SourceAdapter,
    payload: Any,
    *,
    record_store: Any,
    reference_store: Any = None,
    ingested_at: str,
    sensitivity: str = "normal",
) -> dict[str, int]:
    """Sync ingest: records + references only. ``EmittedDocument`` IS routed,
    but only by ``aingest`` (document ingest is embed-bound I/O, so there is no
    sync ingestor seam); ``EmittedEntity`` is unrouted everywhere (Phase 9).
    Both raise here, with distinct messages. Does NOT embed reference
    summaries — the sync path is
    used by the session-records adapter, which never emits references today
    (verified F3), so there is no sync embedder seam. Emitted references
    always land unembedded here; embed them via ``aingest(...,
    reference_embedder=...)`` or backfill with ``set_embeddings``/
    ``count_unembedded``."""
    records_by_source: dict[str, list[Record]] = defaultdict(list)
    refs_by_source: dict[str, list[ReferenceEntry]] = defaultdict(list)

    for item in adapter.emit(payload):
        _check_provenance(item)
        if isinstance(item, EmittedDocument):
            # Routed — but only on the async seam: document ingest is embed-bound
            # I/O, so there is no sync `document_ingestor`. Saying "not routed"
            # here would send a caller looking for a feature that exists.
            raise NotImplementedError(
                "EmittedDocument is an async-only tier — "
                "use `aingest(..., document_ingestor=...)`"
            )
        if isinstance(item, EmittedEntity):
            raise NotImplementedError(
                "EmittedEntity tier is declared but not routed (Phase 9)"
            )
        _route_record_or_reference(
            item, records_by_source, refs_by_source, ingested_at, sensitivity
        )

    n_rec, n_ref = _persist_records_and_refs(
        records_by_source, refs_by_source, record_store, reference_store
    )
    return {"records": n_rec, "references": n_ref}


async def aingest(
    adapter: SourceAdapter,
    payload: Any,
    *,
    record_store: Any,
    reference_store: Any = None,
    document_ingestor: Any = None,
    reference_embedder: Any = None,
    identity_store: Any = None,
    ingested_at: str,
    sensitivity: str = "normal",
) -> dict[str, Any]:
    """Async ingest seam: all tiers. Records/references behave exactly like
    ``ingest``; ``EmittedDocument`` routes to the ``document_ingestor``
    (``DocumentIngestService``); ``EmittedEntity`` routes to the
    ``identity_store`` (``IdentityStore``) as a person + its aliases + an
    optional external-key link. When ``reference_embedder`` is bound (an
    ``embed_chunks``-protocol object, same interface ``DocumentIngestService``
    uses), emitted reference summaries are embedded and attached via
    ``ReferenceCatalogStore.set_embeddings`` after the upsert; when it is
    None, references still land — just unembedded (A1-compatible degrade,
    backfillable later via ``count_unembedded``/``set_embeddings``).

    An ``EmittedEntity`` with no ``identity_store`` bound is a hard
    ``ProvenanceError`` — mirroring the ``document_ingestor`` branch, and no
    longer the Phase-9 ``NotImplementedError`` (the sync ``ingest`` still
    raises it: entities are an async-only tier for the same reason documents
    are). Each entity becomes one ``upsert_person`` (sensitivity inherited
    from this call), one global (``scope=None``) ``upsert_alias`` per
    ``aliases[]`` entry, and — when ``external_ref`` is set — one
    ``add_link(ref_kind="external")`` binding the person to that opaque key
    (voice cluster / phone number). Scoped aliases are a Task 7 API concern.

    Return dict keys: ``records``, ``references``, ``documents``, ``entities``
    (counts, existing keys unchanged for backward compatibility) plus
    ``documents_by_source`` (``dict[str, list[str]]``) — the chunk ids the
    document tier produced, grouped by ``source_id``, passed through from
    ``DocumentIngestService.ingest_documents``'s ``chunks_by_source`` (G5
    A2). Empty when no ``EmittedDocument`` items were emitted."""
    from brainpalace_server.services.document_ingest_service import IngestDoc

    records_by_source: dict[str, list[Record]] = defaultdict(list)
    refs_by_source: dict[str, list[ReferenceEntry]] = defaultdict(list)
    docs: list[IngestDoc] = []
    entities: list[EmittedEntity] = []

    for item in adapter.emit(payload):
        _check_provenance(item)
        if isinstance(item, EmittedDocument):
            if document_ingestor is None:
                raise ProvenanceError(
                    "document items emitted but no document_ingestor bound"
                )
            docs.append(
                IngestDoc(
                    text=item.text,
                    metadata=dict(item.metadata),
                    domain=item.domain,
                    source=item.source,
                    source_id=item.source_id,
                    sensitivity=item.sensitivity,
                )
            )
        elif isinstance(item, EmittedEntity):
            if identity_store is None:
                raise ProvenanceError(
                    "entity items emitted but no identity_store bound"
                )
            # Accumulate; apply after the drain so a later provenance failure
            # leaves the identity store untouched (mirrors the record/ref and
            # document tiers — nothing is written until the emit stream is
            # fully validated).
            entities.append(item)
        else:
            _route_record_or_reference(
                item, records_by_source, refs_by_source, ingested_at, sensitivity
            )

    n_rec, n_ref = _persist_records_and_refs(
        records_by_source, refs_by_source, record_store, reference_store
    )

    if reference_embedder is not None and refs_by_source:
        all_refs = [r for refs in refs_by_source.values() for r in refs]
        if all_refs:
            pieces = [_SummaryPiece(text=r.summary) for r in all_refs]
            embeddings = await reference_embedder.embed_chunks(pieces)
            reference_store.set_embeddings(
                list(zip((r.id for r in all_refs), embeddings))
            )

    n_docs = 0
    documents_by_source: dict[str, list[str]] = {}
    if docs:
        result = await document_ingestor.ingest_documents(
            docs, sensitivity=sensitivity, ingested_at=ingested_at
        )
        n_docs = result["chunks_new"] + result["chunks_kept"]
        documents_by_source = result.get("chunks_by_source", {})

    n_entities = _persist_entities(entities, identity_store, ingested_at, sensitivity)

    return {
        "records": n_rec,
        "references": n_ref,
        "documents": n_docs,
        "documents_by_source": documents_by_source,
        "entities": n_entities,
    }


def _persist_entities(
    entities: list[EmittedEntity],
    identity_store: Any,
    ingested_at: str,
    sensitivity: str,
) -> int:
    """Land each accumulated ``EmittedEntity`` as a person + its global aliases
    + an optional external-key link. Returns the person count. The presence of
    an ``identity_store`` was already enforced at emit time, so this is only
    reached with a bound store."""
    n = 0
    for ent in entities:
        person_id = identity_store.upsert_person(
            Person(
                name=ent.name,
                kind=ent.kind,
                domain=ent.domain,
                sensitivity=sensitivity,
            )
        )
        for surface in ent.aliases:
            identity_store.upsert_alias(Alias(surface=surface, person_id=person_id))
        if ent.external_ref:
            identity_store.add_link(
                Link(
                    ref=ent.external_ref,
                    ref_kind="external",
                    # An opaque external key identifies a person across a
                    # source's utterances; participant is the D5 role that
                    # carries an external ref. method is user_asserted: an
                    # adapter emitting this binding is asserting it, not
                    # inferring an attribution at read time (D6).
                    role="participant",
                    method="user_asserted",
                    at=ingested_at,
                    person_id=person_id,
                )
            )
        n += 1
    return n
