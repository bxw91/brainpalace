"""Git-history indexing endpoints (Phase 130 — git-history-indexing)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from brainpalace_server.config.git_config import load_git_indexing_config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/reindex",
    summary="Re-index git history",
    description="Ingest (or incrementally refresh) this project's git commit "
    "history into the index. Opt-in: returns 503 unless git indexing is enabled.",
)
async def reindex_git(request: Request) -> dict[str, Any]:
    svc = getattr(request.app.state, "git_index_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Git indexing is disabled (set git_indexing.enabled: true in "
            "config.yaml, and GIT_INDEXING_ENABLED is not false).",
        )

    cfg = getattr(request.app.state, "git_indexing_config", None)
    if cfg is None:
        cfg = load_git_indexing_config()
    project_root = getattr(request.app.state, "project_root", "") or ""

    summary: dict[str, Any] = await svc.index_repo(project_root, cfg)
    logger.info(
        "Git reindex: %d new commit(s), %d skipped",
        summary.get("commits_new", 0),
        summary.get("skipped", 0),
    )
    return summary
