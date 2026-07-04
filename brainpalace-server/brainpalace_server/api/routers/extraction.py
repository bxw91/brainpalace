"""Extraction drain endpoints (Plan 3) — the HTTP face of the pending queue.

GET /extraction/pending — bounded batch from the shared pending queue (docs +
sessions), for the CC subagent executor (spec §7). POST /extraction/submit —
generalized submit: doc triplets → graph + mark_done; session → store + marker.

Trust model (finding 3-3): like the rest of the API these endpoints are
**unauthenticated**, and the write path (`POST /extraction/submit`) mutates the
knowledge graph and, for `source=session`, spends embedding budget. They are safe
only under BrainPalace's default **loopback bind** (`bind_host` 127.0.0.1).
Binding a non-loopback address (`--host 0.0.0.0`) exposes the write path to anyone
on the network with no auth — only do so behind a trusted network / reverse-proxy
auth. There is no per-endpoint auth here by design.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from brainpalace_server.config import settings
from brainpalace_server.indexing import get_embedding_generator
from brainpalace_server.models.extraction_api import (
    ExtractionSubmit,
    PendingBatch,
    PendingItem,
    SubmitResult,
)
from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.entity_resolver import link_kwargs
from brainpalace_server.services.session_distill_service import (
    pending_sessions,
    write_marker,
)
from brainpalace_server.services.session_extract_service import SessionExtractService
from brainpalace_server.storage.graph_store import get_graph_store_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Bounds (finding 3-7) — the queue endpoints are localhost-trusted, but a buggy
# client or a typo'd limit must not load an unbounded batch (with chunk text) into
# memory or flood add_triplet. limit=0 (the SessionStart count path) stays valid.
_MAX_PENDING_LIMIT = 100
_MAX_TRIPLETS = 1000


@router.get(
    "/pending",
    response_model=PendingBatch,
    summary="Bounded batch of pending extraction items",
)
async def get_pending(
    request: Request, limit: int = 20, source: str = "all"
) -> PendingBatch:
    """Return up to ``limit`` items awaiting graph extraction (docs + sessions)."""
    if source not in {"all", "doc", "session"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source must be one of: all, doc, session",
        )
    limit = max(0, min(limit, _MAX_PENDING_LIMIT))  # 3-7: clamp
    doc_items: list[PendingItem] = []
    session_items: list[PendingItem] = []
    doc_total = 0
    store = getattr(request.app.state, "doc_pending_store", None)
    if store is not None:
        doc_total = store.count_pending()
        # Surface doc chunks to the (free) subagent executor only when the engine
        # mode invites it — subagent/auto — and graphrag is on. provider mode
        # drains server-side (reconciler), so it is NOT offered to the subagent;
        # off offers nothing. Absent state (bare test app) defaults safe-on so the
        # raw queue endpoint still works. doc_pending_total stays unconditional.
        mode_doc = getattr(request.app.state, "extraction_mode_doc", "subagent")
        graphrag_on = bool(getattr(request.app.state, "graphrag_enabled", True))
        doc_surfaceable = graphrag_on and mode_doc in ("subagent", "auto")
        if source in ("all", "doc") and doc_surfaceable:
            for chunk_id, text in store.select_pending(limit):
                doc_items.append(PendingItem(source="doc", id=chunk_id, text=text))
    # Sessions gate on the engine mode exactly like docs: surface to the (free)
    # subagent executor only in subagent/auto. provider drains server-side (the
    # distiller), so it is NOT offered to the subagent; off offers nothing.
    # Absent state (bare test app) defaults safe-on so the raw queue still works.
    mode_session = getattr(request.app.state, "extraction_mode_session", "subagent")
    session_surfaceable = mode_session in ("subagent", "auto")
    if source in ("all", "session") and session_surfaceable:
        project_root = getattr(request.app.state, "project_root", None)
        archive_dir = getattr(request.app.state, "extraction_archive_dir", None)
        if project_root and archive_dir:
            for sid, path in pending_sessions(project_root, archive_dir)[:limit]:
                session_items.append(PendingItem(source="session", id=sid, path=path))

    # Round-robin interleave so a large doc backlog can never crowd sessions
    # out of the shared queue (and vice versa) — spec §7 / OQ5 (one queue).
    items: list[PendingItem] = []
    di = iter(doc_items)
    si = iter(session_items)
    while len(items) < limit:
        progressed = False
        for src in (di, si):
            nxt = next(src, None)
            if nxt is not None:
                items.append(nxt)
                progressed = True
                if len(items) >= limit:
                    break
        if not progressed:
            break
    return PendingBatch(items=items, doc_pending_total=doc_total)


@router.get("/text/{chunk_id}", summary="Text of one pending doc chunk")
async def get_chunk_text(chunk_id: str, request: Request) -> dict[str, str]:
    store = getattr(request.app.state, "doc_pending_store", None)
    text = store.get_text(chunk_id) if store is not None else None
    if text is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no pending text for chunk_id",
        )
    return {"chunk_id": chunk_id, "text": text}


@router.post(
    "/submit", response_model=SubmitResult, summary="Submit an extraction payload"
)
async def submit(payload: ExtractionSubmit, request: Request) -> SubmitResult:
    if payload.source == "doc":
        if not payload.chunk_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chunk_id required for source=doc",
            )
        if payload.triplets and len(payload.triplets) > _MAX_TRIPLETS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"too many triplets (max {_MAX_TRIPLETS})",  # 3-7
            )
        store = getattr(request.app.state, "doc_pending_store", None)
        # Early already-done guard (H4/E4): if the chunk is no longer pending
        # (provider drained it between the subagent fetching it and submitting),
        # skip all graph writes and return a no-op 200.  mark_done is idempotent
        # so returning marked_done=True is safe — the store already has status=seen.
        if store is not None and store.get_text(payload.chunk_id) is None:
            logger.debug(
                "extraction.submit: chunk %s already done — skipping (late subagent)",
                payload.chunk_id,
            )
            return SubmitResult(
                source="doc",
                id=payload.chunk_id,
                triplets_stored=0,
                marked_done=True,
            )
        graph = get_graph_store_manager()
        project_root = str(getattr(request.app.state, "project_root", "") or "")
        # §3 doc self-maintenance: purge this chunk's prior triplet set before
        # writing the new one (idempotent re-extraction, no stale buildup).
        graph.invalidate_by_source_file(payload.chunk_id, domain="doc")
        stored = 0
        for t in payload.triplets or []:
            # Plan B: endpoints naming an existing canonical code node link
            # onto it (per-endpoint domains keep the code node in 'code').
            kwargs: dict[str, Any] = {
                "subject_type": t.subject_type,
                "object_type": t.object_type,
                "source_chunk_id": payload.chunk_id,
                "source_file": payload.chunk_id,
                "domain": "doc",
            }
            kwargs.update(
                link_kwargs(
                    t.subject,
                    t.object,
                    t.subject_type,
                    t.object_type,
                    project_root,
                    graph,
                )
            )
            if graph.add_triplet(
                subject=t.subject, predicate=t.predicate, obj=t.object, **kwargs
            ):
                stored += 1
        graph.sweep_orphan_nodes(domain="doc")
        graph.persist()
        # Mark the chunk done when the graph is READY to accept triplets — even
        # if some triplets did not store. A per-triplet failure (malformed entity,
        # store error) is terminal: re-draining re-submits the same triplet → the
        # same add_triplet() False → an endless re-drain loop (finding 3-1). Only
        # leave the chunk pending when the graph itself is not ready (off / not yet
        # initialized) — a transient state a later drain retries.
        requested = len(payload.triplets or [])
        graph_ready = bool(
            settings.ENABLE_GRAPH_INDEX and getattr(graph, "is_initialized", False)
        )
        marked = False
        if store is not None and graph_ready:
            if stored < requested:
                logger.warning(
                    "extraction.submit: stored %d/%d triplets for chunk %s; marking "
                    "done and dropping the rest (re-draining would re-submit the "
                    "same failures)",
                    stored,
                    requested,
                    payload.chunk_id,
                )
            store.mark_done(payload.chunk_id)
            marked = True
        # Subagent channel: record the STORED delta, never the claimed count (§6-F2).
        # The early already-done path above returns stored=0, so a dup submit
        # meters nothing — no double count.
        from brainpalace_server.services.usage_metrics import (
            record_usage,
        )  # noqa: PLC0415

        record_usage("subagent", "", "", "doc", chunks=1, triplets=stored)
        return SubmitResult(
            source="doc",
            id=payload.chunk_id,
            triplets_stored=stored,
            marked_done=marked,
        )

    # source == "session": validate + delegate to the existing store path.
    # Attribute names + call signature mirror the POST /sessions/extract handler.
    if not payload.extraction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="extraction required for source=session",
        )
    # Storage-readiness guard — mirror POST /sessions/extract: fail with a clean
    # 503 instead of a 500 from upsert_documents when the backend isn't ready.
    if getattr(request.app.state, "storage_backend", None) is None or not getattr(
        request.app.state.storage_backend, "is_initialized", False
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage backend not ready.",
        )
    try:
        extraction = SessionExtraction.model_validate(payload.extraction)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid extraction: {exc}",
        ) from exc

    st = request.app.state
    storage_backend = getattr(st, "storage_backend", None)

    # embedder: sessions.py obtains this via get_embedding_generator(), not app.state
    embedder = get_embedding_generator()

    # graph_store: best-effort, same as sessions.py
    graph_store = None
    try:
        if getattr(settings, "ENABLE_GRAPH_INDEX", False):
            graph_store = get_graph_store_manager()
    except Exception:  # noqa: BLE001 — graph optional
        pass

    project_root = getattr(st, "project_root", "") or ""
    # digest_path: derived from project_root, exactly as in sessions.py
    digest_path = (
        str(Path(project_root) / "BRAINPALACE_DECISIONS.md") if project_root else None
    )
    memory_service = getattr(st, "memory_service", None)
    record_store = getattr(st, "record_store", None)

    await SessionExtractService().store(
        extraction,
        embedder=embedder,
        storage_backend=storage_backend,
        graph_store=graph_store,
        digest_path=digest_path,
        memory_service=memory_service,
        project_root=project_root,
        record_store=record_store,
    )
    # Marker write is best-effort I/O — mirror sessions.py and never let an
    # OSError 500 a session whose extraction already stored successfully.
    marked = False
    try:
        write_marker(project_root, extraction.session_id)
        marked = True
    except OSError:
        logger.warning(
            "extraction.submit: write_marker failed for session %s",
            extraction.session_id,
        )
    return SubmitResult(source="session", id=extraction.session_id, marked_done=marked)
