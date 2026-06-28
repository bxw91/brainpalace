"""Usage telemetry aggregation endpoint (read-only). 503 when disabled."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

router = APIRouter()

# window -> (lookback_minutes, series bucket_size_minutes). Buckets are minutes;
# the bucket size keeps the trend readable: fine for short windows, coarse for
# long ones (1h -> per-minute, 30d -> per-6h).
_WINDOWS = {
    "1h": (60, 1),
    "24h": (24 * 60, 15),
    "7d": (7 * 24 * 60, 60),
    "30d": (30 * 24 * 60, 360),
}


@router.get("/usage", summary="Windowed usage/spend telemetry")
async def usage(
    request: Request,
    window: str = Query("24h"),
) -> dict[str, Any]:
    if window not in _WINDOWS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"window must be one of {sorted(_WINDOWS)}",
        )
    store = getattr(request.app.state, "usage_metrics_store", None)
    if store is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Usage metrics are disabled (usage_metrics.enabled=false)",
        )
    lookback, bucket_size = _WINDOWS[window]
    wall_bucket = int(time.time()) // 60  # minute bucket
    # Anchor the window to the newest recorded data, not wall-clock: a quiet
    # hour (no recent activity) still shows the last `lookback` minutes of
    # actual log data instead of an empty chart. Falls back to wall-clock when
    # the store is empty.
    anchor = store.latest_bucket() or wall_bucket
    now_bucket = wall_bucket  # real now: only marks a bar partial if data is current
    since = anchor - lookback
    totals, series = store.aggregate(since_bucket=since, bucket_size=bucket_size)
    # Annotate each backlog row with whether the feature that drains it is on.
    # When off, the queue still fills at index time but never drains, so the
    # dashboard flags the depth as dead weight rather than "work in progress".
    mode_doc = getattr(request.app.state, "extraction_mode_doc", "off")
    mode_session = getattr(request.app.state, "extraction_mode_session", "off")
    queue = store.queue_latest()
    for row in queue:
        src = row.get("source")
        if src in ("doc", "git"):
            row["active"] = mode_doc != "off"
        elif src == "session":
            row["active"] = mode_session != "off"
        else:
            row["active"] = True
    return {
        "window": window,
        "now_bucket": now_bucket,
        "bucket_size": bucket_size,
        "totals": totals,
        "series": series,
        "series_by_source": store.token_series_by_source(
            since_bucket=since, bucket_size=bucket_size
        ),
        "queue": queue,
    }
