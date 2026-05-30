"""Session indexing endpoints (Phase 050 — session-ingest-core)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from brainpalace_server.config.session_config import load_session_indexing_config
from brainpalace_server.models.session_extract import (
    SessionExtraction,
    SessionExtractResult,
)
from brainpalace_server.services.session_extract_service import SessionExtractService

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
            from brainpalace_server.storage.graph_store import get_graph_store_manager

            graph_store = get_graph_store_manager()
    except Exception as exc:  # noqa: BLE001 — graph optional
        logger.debug("graph store unavailable for extract: %s", exc)

    project_root = getattr(request.app.state, "project_root", "") or ""
    digest_path = (
        str(Path(project_root) / "BRAINPALACE_DECISIONS.md") if project_root else None
    )

    memory_service = getattr(request.app.state, "memory_service", None)

    return await SessionExtractService().store(
        payload,
        embedder=embedder,
        storage_backend=storage_backend,
        graph_store=graph_store,
        digest_path=digest_path,
        memory_service=memory_service,
        project_root=project_root,
    )
