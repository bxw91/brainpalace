"""Query endpoints for semantic search."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from brainpalace_server.models import QueryRequest, QueryResponse
from brainpalace_server.models.query import BlockedJobInfo
from brainpalace_server.services.query_log import QueryLogService

logger = logging.getLogger(__name__)

router = APIRouter()


def _log_query(log_service: object, **fields: object) -> None:
    """Best-effort write to the query log. Never raises.

    Logging a query must never break the query itself, so all failures are
    swallowed (debug-logged). A ``None`` service or a service with
    ``enabled == False`` is a no-op.
    """
    try:
        if log_service is not None and getattr(log_service, "enabled", True):
            log_service.record(**fields)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — logging must never break a query
        logger.debug("query log write failed", exc_info=True)


@router.post(
    "/",
    response_model=QueryResponse,
    summary="Query Documents",
    description="Perform semantic, keyword, or hybrid search on indexed documents.",
)
async def query_documents(
    request_body: QueryRequest, request: Request
) -> QueryResponse:
    """Execute a search query on indexed documents.

    Args:
        request_body: QueryRequest containing query parameters.
        request: FastAPI request for accessing app state.

    Returns:
        QueryResponse with ranked results and timing.

    Raises:
        400: Invalid query (empty or too long)
        409: Embedding provider mismatch (re-index required)
        503: Index not ready (indexing in progress or not initialized)
    """
    from brainpalace_server.services import QueryService
    from brainpalace_server.services.indexing_service import IndexingService

    query_service: QueryService = request.app.state.query_service
    indexing_service: IndexingService = request.app.state.indexing_service

    # Validate query
    query = request_body.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query cannot be empty",
        )

    # Check if service is ready
    if not query_service.is_ready():
        if indexing_service.is_indexing:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Index not ready. Indexing is in progress.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Index not ready. Please index documents first.",
            )

    # Check for embedding provider mismatch (PROV-07 query-time guard)
    embedding_warning = getattr(request.app.state, "embedding_warning", None)
    if embedding_warning:
        # Check if it's a dimension mismatch (critical) vs provider/model only
        if "d)" in embedding_warning:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Embedding mismatch: {embedding_warning} "
                    "Re-index with --force to resolve."
                ),
            )

    # Execute query
    try:
        response = await query_service.execute_query(request_body)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {str(e)}",
        ) from e

    # Record to the query history log (fire-and-forget; never breaks a query).
    # QueryResult exposes `source` (file path), `text` (chunk snippet) and
    # `score`; there is no line-range field, so `lines` stays None.
    log_service = getattr(request.app.state, "query_log_service", None)
    _log_query(
        log_service,
        query=query,
        mode=request_body.mode.value,
        top_k=request_body.top_k,
        latency_ms=getattr(response, "query_time_ms", 0.0),
        results=[
            {
                "score": getattr(r, "score", None),
                "path": getattr(r, "source", None),
                "lines": None,
                "snippet": getattr(r, "text", "") or "",
            }
            for r in getattr(response, "results", [])
        ],
        alpha=request_body.alpha,
        filters={
            "source_types": request_body.source_types,
            "languages": request_body.languages,
        },
    )

    # Attach a budget-blocked-index advisory if one exists (fail-soft — a jobs
    # error must never break search).
    job_service = getattr(request.app.state, "job_service", None)
    if job_service is not None:
        try:
            blocked = await job_service.get_blocked_summary()
        except Exception:  # noqa: BLE001 — advisory only, never break search
            blocked = None
        if blocked:
            response.index_blocked = BlockedJobInfo(**blocked)

    return response


@router.get(
    "/count",
    summary="Document Count",
    description="Get the total number of indexed document chunks.",
)
async def get_document_count(request: Request) -> dict[str, int | bool]:
    """Get the total number of indexed document chunks.

    Args:
        request: FastAPI request for accessing app state.

    Returns:
        Dictionary with count of indexed chunks.
    """
    query_service = request.app.state.query_service

    count = await query_service.get_document_count()

    return {
        "total_chunks": count,
        "ready": query_service.is_ready(),
    }


@router.get(
    "/history",
    summary="Query History",
    description="List recent queries (newest first) without result payloads.",
)
async def query_history(
    request: Request,
    since: float | None = None,
    mode: str | None = None,
    contains: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List recent queries from the per-project history log.

    Returns an empty list when the query log is disabled or unavailable.
    """
    log: QueryLogService | None = getattr(request.app.state, "query_log_service", None)
    if log is None:
        return []
    return log.list_recent(
        since=since, mode=mode, contains=contains, limit=limit, offset=offset
    )


@router.get(
    "/stats",
    summary="Query Analytics",
    description="Aggregated analytics over the query history log: totals, mode "
    "distribution, latency percentiles + trend, top and zero-result queries.",
)
async def query_stats(
    request: Request,
    since: float | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Aggregate stats; an empty shape when the query log is disabled."""
    log: QueryLogService | None = getattr(request.app.state, "query_log_service", None)
    if log is None:
        return {
            "total": 0,
            "zero_result_count": 0,
            "mode_distribution": {},
            "latency": {"p50": 0.0, "p95": 0.0, "avg": 0.0},
            "latency_trend": [],
            "top_queries": [],
            "zero_result_queries": [],
        }
    return log.stats(since=since, top_n=top_n)


@router.get(
    "/history/{qid}",
    summary="Query History Detail",
    description="Return a single logged query including its truncated results.",
)
async def query_history_detail(request: Request, qid: str) -> dict[str, Any]:
    """Return one logged query (with results) or 404 if unknown."""
    log: QueryLogService | None = getattr(request.app.state, "query_log_service", None)
    detail = log.get(qid) if log is not None else None
    if detail is None:
        raise HTTPException(status_code=404, detail="query not found")
    return detail
