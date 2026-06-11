"""Git-history indexing endpoints (Phase 130 — git-history-indexing)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/reindex",
    summary="Re-index git history",
    description="Enqueue an incremental git-history ingest job. "
    "Returns a job_id immediately; progress visible via GET /jobs/{job_id}. "
    "Opt-in: returns 503 unless git indexing is enabled.",
)
async def reindex_git(request: Request) -> dict[str, Any]:
    svc = getattr(request.app.state, "git_index_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Git indexing is disabled (set git_indexing.enabled: true in "
            "config.yaml, and GIT_INDEXING_ENABLED is not false).",
        )

    job_service = getattr(request.app.state, "job_service", None)
    if job_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue service is not available.",
        )

    project_root = getattr(request.app.state, "project_root", "") or ""
    if not project_root:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Git indexing is not available: no project root is configured.",
        )

    resp = await job_service.enqueue_git_history_job(project_root)
    logger.info(
        "Git reindex enqueued: job_id=%s dedupe_hit=%s",
        resp.job_id,
        resp.dedupe_hit,
    )
    result: dict[str, Any] = resp.model_dump()
    return result
