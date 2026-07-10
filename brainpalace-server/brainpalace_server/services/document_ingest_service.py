"""Programmatic text ingest (spec Item 3 / gaps G1+G2).

Mirrors SessionIndexService's chunk→dedup→budget→embed→upsert pattern for
caller-supplied text with full provenance. Replace-source semantics are
embed-frugal: unchanged chunk ids keep their stored embedding but get their
metadata refreshed; stale ids are deleted; only new ids are embedded."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

RESERVED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "domain",
        "source",
        "source_id",
        "ingested_at",
        "sensitivity",
        "text_language",
        "source_type",
        "authority",
        "chunk_index",
    }
)

SOURCE_TYPE_INGEST = "ingest"


class IngestDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    metadata: dict[str, str] = {}
    domain: str
    source: str
    source_id: str
    # D6: optional per-item override of the batch-level `sensitivity` kwarg
    # passed to `ingest_documents` — lets one mixed-sensitivity batch avoid N
    # separate calls. None means "use the batch default".
    sensitivity: str | None = None


def ingest_display_source(domain: str, source: str, source_id: str) -> str:
    return f"ingest://{domain}/{source}/{source_id}"


def _raw_source_from_display(display: str, domain: str, source_id: str) -> str:
    """Recover the caller's raw ``source`` from the stored display URI.

    Chunk metadata stores only the display form
    ``ingest://{domain}/{source}/{source_id}`` under the ``source`` key (the
    raw producing-source label is never stored on its own). Given ``domain``
    and ``source_id`` — both present in the same metadata — the raw ``source``
    is the middle segment, recovered by stripping the known prefix/suffix.
    Falls back to the display string unchanged if it doesn't match the
    expected shape (e.g. legacy or hand-written data)."""
    prefix = f"ingest://{domain}/"
    suffix = f"/{source_id}"
    if display.startswith(prefix) and display.endswith(suffix):
        return display[len(prefix) : len(display) - len(suffix)]
    return display


def _chunk_id(domain: str, source: str, source_id: str, idx: int, text: str) -> str:
    h = hashlib.sha256(
        f"{domain}|{source}|{source_id}|{idx}|{text}".encode()
    ).hexdigest()[:16]
    return f"ing_{h}"


class _Piece(BaseModel):
    """One chunk-to-be: text + its final metadata. `.text` matches the
    embed_chunks protocol (embedders read chunk.text)."""

    text: str
    metadata: dict[str, Any]
    chunk_id: str


class DocumentIngestService:
    def __init__(
        self,
        embedding_generator: Any,
        storage_backend: Any,
        chunker: Any = None,
        bm25_manager: Any = None,
        identity_store: Any = None,
    ) -> None:
        self.embedding_generator = embedding_generator
        self.storage_backend = storage_backend
        self.chunker = chunker  # None => whole text is one chunk
        self.bm25_manager = bm25_manager  # wired in Task 2
        # G5 A3: optional identity store, bound None-safe like bm25_manager. On
        # re-ingest its mention links to changed chunk addresses are stale-marked
        # (never deleted); on delete_source its links for the source are dropped.
        self.identity_store = identity_store

    async def _split(self, doc: IngestDoc) -> list[str]:
        if self.chunker is None:
            return [doc.text] if doc.text.strip() else []
        # ContextAwareChunker path — build the minimal LoadedDocument it needs.
        from brainpalace_server.indexing.document_loader import LoadedDocument

        display = ingest_display_source(doc.domain, doc.source, doc.source_id)
        loaded = LoadedDocument(
            text=doc.text,
            source=display,
            file_name=doc.source_id,
            file_path=display,
            file_size=len(doc.text.encode("utf-8")),
        )
        chunks = await self.chunker.chunk_single_document(loaded)
        return [c.text for c in chunks]

    async def ingest_documents(
        self,
        docs: list[IngestDoc],
        *,
        sensitivity: str = "normal",
        language: str | None = None,
        ingested_at: str | None = None,
    ) -> dict[str, Any]:
        """Chunk, embed-frugally upsert, and return counts + ids.

        Return dict keys:
          - ``chunk_ids``: **all** pieces produced by this call, in order —
            NOT only the newly embedded ones (kept/refreshed chunks are
            included too). The name is a historical misnomer; callers rely
            on it meaning "every piece", so it is not renamed here.
          - ``source_ids``: sorted unique source ids across ``docs``.
          - ``chunks_by_source``: same ids as ``chunk_ids``, grouped by
            ``source_id`` and ordered, so a multi-document caller (e.g.
            ``aingest``) can tell which chunks belong to which source.
        """
        from brainpalace_server.services.indexing_service import (
            enforce_token_budget,
        )
        from brainpalace_server.services.usage_metrics import usage_scope

        stamp = ingested_at or datetime.now(timezone.utc).isoformat()
        pieces: list[_Piece] = []
        source_ids: list[str] = []
        chunks_by_source: dict[str, list[str]] = {}

        for doc in docs:
            clash = RESERVED_METADATA_KEYS & set(doc.metadata)
            if clash:
                raise ValueError(f"metadata uses reserved key(s): {sorted(clash)}")
            source_ids.append(doc.source_id)
            source_chunk_ids = chunks_by_source.setdefault(doc.source_id, [])
            display = ingest_display_source(doc.domain, doc.source, doc.source_id)
            for idx, text in enumerate(await self._split(doc)):
                meta: dict[str, Any] = {
                    **doc.metadata,
                    "domain": doc.domain,
                    "source": display,
                    "source_id": doc.source_id,
                    "ingested_at": stamp,
                    "sensitivity": doc.sensitivity or sensitivity,
                    "source_type": SOURCE_TYPE_INGEST,
                    # 6.5: caller-ingested docs are first-party by definition.
                    "authority": "authoritative",
                    # G5 A1b: stable per-source chunk position, so a link can
                    # address "{source_id}#{idx}" and resolve to the live
                    # chunk_id at read time (chunk_id itself is unstable
                    # across re-ingest because text is part of its hash).
                    "chunk_index": idx,
                }
                if language:
                    meta["text_language"] = language
                cid = _chunk_id(doc.domain, doc.source, doc.source_id, idx, text)
                pieces.append(_Piece(text=text, metadata=meta, chunk_id=cid))
                source_chunk_ids.append(cid)

        new_ids = [p.chunk_id for p in pieces]

        # Stale chunks: previously stored for these source_ids, id not re-produced.
        deleted = 0
        all_stale: set[str] = set()
        for sid in set(source_ids):
            stored = await self.storage_backend.get_ids_by_where(
                {"$and": [{"source_type": SOURCE_TYPE_INGEST}, {"source_id": sid}]}
            )
            stale = stored - set(new_ids)
            if stale:
                deleted += await self.storage_backend.delete_by_ids(list(stale))
                all_stale |= stale
        # Keep BM25 consistent with the vector store: stale ids must also leave
        # the bm25 corpus or re-ingesting changed text leaves stale bm25/hybrid
        # hits. Best-effort (BM25 is non-canonical), like the other hooks.
        if self.bm25_manager is not None and all_stale:
            self._remove_bm25(list(all_stale))

        existing = await self.storage_backend.get_existing_ids(new_ids)
        to_embed = [p for p in pieces if p.chunk_id not in existing]
        kept = [p for p in pieces if p.chunk_id in existing]

        if self.identity_store is not None:
            # G5 A3/Task 6: `existing` is the set of pieces whose (idx, text)
            # is UNCHANGED (their hash matches what's already stored) — i.e.
            # the chunk positions that are still "alive". Any role='mentioned'
            # link addressing a position NOT in this set has had its
            # underlying text moved/changed/removed, so its recorded span is
            # no longer trustworthy — stale-mark it (never delete). Untouched
            # speaker/participant links survive because stale_mark only
            # touches role='mentioned'.
            alive_refs_by_source: dict[str, set[str]] = {}
            for p in pieces:
                if p.chunk_id in existing:
                    sid = p.metadata["source_id"]
                    idx = p.metadata["chunk_index"]
                    alive_refs_by_source.setdefault(sid, set()).add(f"{sid}#{idx}")
            for sid in set(source_ids):
                self.identity_store.stale_mark(
                    sid, alive_refs=alive_refs_by_source.get(sid, set())
                )

        if to_embed:
            try:
                from brainpalace_server.config.indexing_config import (
                    load_indexing_config,
                )

                budget = load_indexing_config().max_embed_tokens_per_job
                enforce_token_budget(to_embed, limit=budget, force=False)
            except ImportError:  # config module name drifted — budget optional
                logger.warning("token budget config not found; skipping budget check")
            with usage_scope("ingest"):
                embeddings = await self.embedding_generator.embed_chunks(to_embed)
            await self.storage_backend.upsert_documents(
                ids=[p.chunk_id for p in to_embed],
                embeddings=embeddings,
                documents=[p.text for p in to_embed],
                metadatas=[p.metadata for p in to_embed],
            )

        # Metadata refresh for kept chunks — reuse the stored embedding.
        for p in kept:
            row = await self.storage_backend.get_by_id(p.chunk_id)
            if row is None:
                continue
            await self.storage_backend.upsert_documents(
                ids=[p.chunk_id],
                embeddings=[row["embedding"]],
                documents=[p.text],
                metadatas=[p.metadata],
            )

        if self.bm25_manager is not None and pieces:
            self._update_bm25(pieces)  # Task 2

        return {
            "chunks_new": len(to_embed),
            "chunks_kept": len(kept),
            "chunks_deleted": deleted,
            "chunk_ids": new_ids,
            "source_ids": sorted(set(source_ids)),
            "chunks_by_source": chunks_by_source,
        }

    def _update_bm25(self, pieces: list[_Piece]) -> None:
        try:
            self.bm25_manager.add_chunks(
                [
                    {"node_id": p.chunk_id, "text": p.text, "metadata": p.metadata}
                    for p in pieces
                ]
            )
        except Exception:  # noqa: BLE001 — BM25 is best-effort, vector is canonical
            logger.exception("BM25 add_chunks failed; ingest continues")

    async def delete_source(self, source_id: str) -> dict[str, Any]:
        stored = await self.storage_backend.get_ids_by_where(
            {"$and": [{"source_type": SOURCE_TYPE_INGEST}, {"source_id": source_id}]}
        )
        n = await self.storage_backend.delete_by_ids(list(stored)) if stored else 0
        if self.bm25_manager is not None and stored:
            self._remove_bm25(list(stored))  # Task 2
        if self.identity_store is not None:
            # G5 A3: drop this source's links (persons + aliases survive —
            # they are user-asserted ground truth, not derived from the text).
            self.identity_store.delete_by_source(source_id)
        return {"chunks_deleted": n}

    def _remove_bm25(self, chunk_ids: list[str]) -> None:
        try:
            self.bm25_manager.remove_chunks(chunk_ids)
        except Exception:  # noqa: BLE001
            logger.exception("BM25 remove_chunks failed; delete continues")

    async def list_sources(
        self,
        *,
        domain: str | None = None,
        source: str | None = None,
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Round 4 D5 — enumerate distinct ingested ``source_id``s.

        Mirrors the delete path's where-lookup: ``get_ids_by_where`` over the
        ingest ``source_type`` (with the ``domain`` filter pushed into the
        where clause, since ``domain`` is a stored key), then reads each
        chunk's metadata to group by ``source_id`` and report ``domain``,
        ``source``, ``chunk_count`` and ``ingested_at``.

        The raw ``source`` (the caller's producing-source label) is NOT a
        stored metadata key — only the display URI
        ``ingest://{domain}/{source}/{source_id}`` is, under ``source``. It is
        recovered deterministically by stripping the known ``domain`` prefix
        and ``source_id`` suffix (:func:`_raw_source_from_display`), so the
        ``source`` filter and the reported ``source`` both use the raw label.

        Sensitivity default-deny: a chunk marked ``sensitivity != 'normal'`` is
        skipped unless ``include_sensitive`` — same semantics as query/
        references. A source whose only chunks are sensitive therefore
        disappears from the default listing entirely.
        """
        if domain is not None:
            where: dict[str, Any] = {
                "$and": [{"source_type": SOURCE_TYPE_INGEST}, {"domain": domain}]
            }
        else:
            where = {"source_type": SOURCE_TYPE_INGEST}
        ids = await self.storage_backend.get_ids_by_where(where)

        grouped: dict[str, dict[str, Any]] = {}
        for cid in ids:
            row = await self.storage_backend.get_by_id(cid)
            if row is None:
                continue
            meta = row.get("metadata") or {}
            if (
                not include_sensitive
                and str(meta.get("sensitivity", "normal")) != "normal"
            ):
                continue
            sid = meta.get("source_id")
            if sid is None:
                continue
            dom = str(meta.get("domain", ""))
            raw_source = _raw_source_from_display(
                str(meta.get("source", "")), dom, str(sid)
            )
            if source is not None and raw_source != source:
                continue
            entry = grouped.get(sid)
            if entry is None:
                grouped[sid] = {
                    "source_id": sid,
                    "domain": dom,
                    "source": raw_source,
                    "chunk_count": 1,
                    "ingested_at": meta.get("ingested_at"),
                }
            else:
                entry["chunk_count"] += 1
                # Keep the most recent ingested_at across the source's chunks.
                stamp = meta.get("ingested_at")
                if stamp is not None and (
                    entry["ingested_at"] is None or stamp > entry["ingested_at"]
                ):
                    entry["ingested_at"] = stamp
        return [grouped[k] for k in sorted(grouped)]

    async def get_source_chunks(
        self,
        source_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Round 4 D5 — return one source's ingested chunks, paginated.

        ``get_ids_by_where`` (same where-lookup the delete path uses) collects
        the source's chunk ids; each is read for ``text``/``metadata`` and
        ordered by ``chunk_index`` (then id) for a stable page. ``total`` is
        the post-sensitivity-filter count so ``offset``/``limit`` page over the
        rows the caller can actually see. Sensitivity default-deny applies as
        in :meth:`list_sources`. An unknown/empty ``source_id`` yields an empty
        ``chunks`` list (total 0) — never a 404.
        """
        ids = await self.storage_backend.get_ids_by_where(
            {"$and": [{"source_type": SOURCE_TYPE_INGEST}, {"source_id": source_id}]}
        )
        rows: list[dict[str, Any]] = []
        for cid in ids:
            row = await self.storage_backend.get_by_id(cid)
            if row is None:
                continue
            meta = row.get("metadata") or {}
            if (
                not include_sensitive
                and str(meta.get("sensitivity", "normal")) != "normal"
            ):
                continue
            rows.append(
                {
                    "chunk_id": cid,
                    "text": row.get("text", ""),
                    "metadata": meta,
                    "_idx": meta.get("chunk_index", 0),
                }
            )
        rows.sort(key=lambda r: (r["_idx"], r["chunk_id"]))
        total = len(rows)
        page = rows[offset : offset + limit]
        for r in page:
            r.pop("_idx", None)
        return {
            "source_id": source_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "chunks": page,
        }


async def forget_source(
    source_id: str,
    *,
    document_ingest_service: DocumentIngestService | None = None,
    record_store: Any = None,
    reference_store: Any = None,
) -> dict[str, Any]:
    """Round 4 D2 — full forget: cascade a delete across all three tiers for
    one ``source_id`` and report per-tier counts.

    Each tier is optional so a keyless server (no ``document_ingest_service``)
    or a caller that only wired some stores still gets a best-effort forget
    over whichever tiers are present, rather than an all-or-nothing failure.
    Document-chunk deletion goes through ``DocumentIngestService.delete_source``,
    which already drops this source's identity links (persons/aliases survive
    — user-asserted ground truth, not derived from the deleted text)."""
    chunks_deleted = 0
    if document_ingest_service is not None:
        doc_result = await document_ingest_service.delete_source(source_id)
        chunks_deleted = doc_result["chunks_deleted"]
    records_deleted = (
        record_store.delete_by_source(source_id) if record_store is not None else 0
    )
    references_deleted = (
        reference_store.delete_by_source(source_id)
        if reference_store is not None
        else 0
    )
    return {
        "chunks_deleted": chunks_deleted,
        "records_deleted": records_deleted,
        "references_deleted": references_deleted,
    }
