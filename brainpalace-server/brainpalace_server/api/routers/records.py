"""Records API router — stats and revalidation endpoints (Task 15)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_record_store(request: Request) -> Any:
    rs = getattr(request.app.state, "record_store", None)
    if rs is None:
        raise HTTPException(
            status_code=503,
            detail="RecordStore is not available on this server.",
        )
    return rs


@router.get(
    "/stats",
    summary="Record store statistics",
    description=(
        "Returns total record count, number of unverified records "
        "(confidence < 0.7), and the list of distinct metric names."
    ),
)
async def records_stats(request: Request) -> dict[str, Any]:
    """GET /records/stats → {total, unverified, metrics}."""
    rs = _get_record_store(request)
    return {
        "total": rs.record_count(),
        "unverified": rs.count_unverified(),
        "metrics": rs.distinct_metrics(),
    }


@router.post(
    "/revalidate",
    summary="Revalidate low-confidence records",
    description=(
        "Re-scores all records whose confidence is below the threshold (0.7). "
        "An optional ``metric`` field restricts rescoring to that metric only. "
        "Returns the number of records rescored."
    ),
)
async def records_revalidate(body: dict[str, Any], request: Request) -> dict[str, int]:
    """POST /records/revalidate {metric?} → {rescored: int}."""
    from brainpalace_server.indexing.record_validation import score_confidence

    rs = _get_record_store(request)
    rescored = rs.revalidate(score_confidence, metric=body.get("metric"))
    return {"rescored": rescored}
