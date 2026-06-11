"""Session indexing endpoints (Phase 050 — session-ingest-core)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from brainpalace_server.config.session_config import load_session_indexing_config
from brainpalace_server.indexing.session_loader import first_user_prompt_line
from brainpalace_server.models.session_extract import (
    SessionExtraction,
    SessionExtractResult,
)
from brainpalace_server.services.session_extract_service import SessionExtractService
from brainpalace_server.storage.graph_store import get_graph_store_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/reindex",
    summary="Re-index session transcripts",
    description="Ingest (or refresh) this project's runtime session transcripts "
    "into the index. Opt-in: returns 503 unless session indexing is enabled.",
)
async def reindex_sessions(request: Request) -> dict[str, Any]:
    svc = getattr(request.app.state, "session_index_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session indexing is disabled (set session_indexing.enabled: "
            "true in config.yaml, and SESSION_INDEXING_ENABLED is not false).",
        )

    cfg = getattr(request.app.state, "session_indexing_config", None)
    if cfg is None:
        cfg = load_session_indexing_config()
    project_root = getattr(request.app.state, "project_root", "") or ""

    summary: dict[str, Any] = await svc.index_project(project_root, cfg)
    logger.info(
        "Session reindex: %d file(s), %d skipped (old)",
        summary.get("files", 0),
        summary.get("files_skipped_old", 0),
    )
    return summary


@router.post(
    "/extract",
    response_model=SessionExtractResult,
    summary="Persist a session extraction payload",
    description="Store a structured extraction (summary + decisions + triplets) "
    "produced by the AI coding tool. No server-side LLM. Idempotent on "
    "session_id.",
)
async def extract_session(
    payload: SessionExtraction, request: Request
) -> SessionExtractResult:
    storage_backend = getattr(request.app.state, "storage_backend", None)
    if storage_backend is None or not storage_backend.is_initialized:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage backend not ready.",
        )

    from brainpalace_server.indexing import get_embedding_generator

    embedder = get_embedding_generator()

    # Graph is best-effort: only attach when graph indexing is enabled.
    graph_store = None
    try:
        from brainpalace_server.config import settings

        if getattr(settings, "ENABLE_GRAPH_INDEX", False):
            graph_store = get_graph_store_manager()
    except Exception as exc:  # noqa: BLE001 — graph optional
        logger.debug("graph store unavailable for extract: %s", exc)

    project_root = getattr(request.app.state, "project_root", "") or ""
    digest_path = (
        str(Path(project_root) / "BRAINPALACE_DECISIONS.md") if project_root else None
    )

    memory_service = getattr(request.app.state, "memory_service", None)

    result = await SessionExtractService().store(
        payload,
        embedder=embedder,
        storage_backend=storage_backend,
        graph_store=graph_store,
        digest_path=digest_path,
        memory_service=memory_service,
        project_root=project_root,
    )
    # Unified marker: any stored extraction (subagent submit OR provider distil)
    # marks the session done, so `auto` engine flips never re-summarize it.
    if project_root:
        try:
            from brainpalace_server.services.session_distill_service import write_marker

            write_marker(project_root, payload.session_id)
        except OSError:
            pass
    return result


class DistillRequest(BaseModel):
    """Paths to (re-)distil via the provider engine (Phase 080, backfill)."""

    paths: list[str] = Field(default_factory=list)
    force: bool = Field(
        default=False,
        description="Re-distil even already-marked sessions (bypass dedup + "
        "quiescence).",
    )


@router.post(
    "/distill",
    summary="Enqueue provider-engine distillation of transcripts",
    description="Schedule the server to summarize the given archived transcripts "
    "(provider mode only). Reuses the same distiller as the live watcher; each "
    "distill is gated quiescent + un-marked unless --force. 503 when the provider "
    "engine is not active (mode != provider or SESSION_DISTILL_ENABLED=false).",
)
async def distill_sessions(req: DistillRequest, request: Request) -> dict[str, Any]:
    distiller = getattr(request.app.state, "session_distiller", None)
    if distiller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider distiller not active (session_extraction.mode is not "
            "'provider', or SESSION_DISTILL_ENABLED=false).",
        )
    enqueued = 0
    for path in req.paths:
        distiller.schedule(path, force=req.force)
        enqueued += 1
    logger.info("Session distill: enqueued %d (force=%s)", enqueued, req.force)
    return {"enqueued": enqueued, "force": req.force}


@router.get(
    "/archive",
    summary="List archived sessions",
    description="Metadata for each archived session transcript (id, path, "
    "mtime, size) plus archive totals. Raw transcript CONTENT is deliberately "
    "not exposed — archives hold full conversations incl. potential secrets. "
    "503 when the session archive is disabled.",
)
async def list_archive(request: Request) -> dict[str, Any]:
    svc = getattr(request.app.state, "session_archive_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session archive is disabled (SESSION_ARCHIVE_ENABLED=false "
            "or no session_indexing.archive config).",
        )
    sessions = []
    for sid, path, mtime in svc.iter_sessions():
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        # Derive a human-readable title from the first prompt line so the
        # dashboard shows what the session was about instead of an opaque id.
        # (Only the first line of the first user turn — not full transcript
        # content, which the archive deliberately never exposes.)
        title = first_user_prompt_line(path)
        sessions.append(
            {
                "session_id": sid,
                "title": title,
                "archive_path": str(path),
                "mtime": mtime,
                "size_bytes": size_bytes,
            }
        )
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return {"sessions": sessions, **svc.stats()}


@router.get(
    "/decisions",
    summary="Browse Decision nodes",
    description="Decision entities from the session knowledge graph, optionally "
    "name-filtered. Empty on the simple graph backend or when graph indexing "
    "is disabled.",
)
async def list_decisions(
    request: Request,
    contains: str | None = None,
    limit: int = Query(50, ge=1, le=1000),
) -> dict[str, Any]:
    mgr = get_graph_store_manager()
    # Cold-start safety: nothing in lifespan initializes the graph store, so a
    # freshly restarted server would silently return [] despite a populated
    # graph_store.db. initialize() is idempotent and a no-op when disabled.
    mgr.initialize()
    return {"decisions": mgr.nodes_by_label("Decision", contains=contains, limit=limit)}


@router.get(
    "/timeline",
    summary="Entity decision timeline",
    description="Temporal edge history (valid_from/valid_until, supersessions) "
    "for one entity, names resolved. Empty on the simple graph backend or when "
    "graph indexing is disabled.",
)
async def entity_timeline(request: Request, entity: str) -> dict[str, Any]:
    mgr = get_graph_store_manager()
    # Cold-start safety: see list_decisions above.
    mgr.initialize()
    return {"entity": entity, "timeline": mgr.timeline_named(entity)}
