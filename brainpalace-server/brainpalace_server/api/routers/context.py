"""Session-start context endpoint (Phase 035 — memory-injection)."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from brainpalace_server.models.context import SessionContext
from brainpalace_server.services.session_context_service import SessionContextService

logger = logging.getLogger(__name__)

router = APIRouter()


def _read_branch(project_root: str | None) -> str | None:
    """Best-effort current branch from .git/HEAD (no subprocess)."""
    if not project_root:
        return None
    head = Path(project_root) / ".git" / "HEAD"
    try:
        content = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if content.startswith("ref:"):
        return content.split("/", 2)[-1]  # refs/heads/<branch>
    return content[:12]  # detached HEAD → short sha


@router.get(
    "/session-start",
    response_model=SessionContext,
    summary="Session-start context block",
    description="Frozen-snapshot context (project facts + curated memory) for "
    "injection at session start.",
)
async def session_start(request: Request) -> SessionContext:
    svc: SessionContextService | None = getattr(
        request.app.state, "session_context_service", None
    )
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session context is disabled (CONTEXT_ENABLED=false).",
        )

    project_root = getattr(request.app.state, "project_root", "") or None
    branch = _read_branch(project_root)

    doc_count: int | None = None
    query_service = getattr(request.app.state, "query_service", None)
    if query_service is not None:
        try:
            doc_count = await query_service.get_document_count()
        except Exception as exc:  # noqa: BLE001 — context must never fail hard
            logger.warning("session context: doc count failed: %s", exc)

    return svc.build(project_root=project_root, branch=branch, doc_count=doc_count)
