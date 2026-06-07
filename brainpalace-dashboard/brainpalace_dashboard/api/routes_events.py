"""Server-Sent Events stream for live dashboard updates.

A single ``GET /dashboard/api/events`` stream emits an ``instances`` event
(the current fleet list) every ``poll_s`` seconds. The SPA subscribes once via
``EventSource`` and feeds each payload into its TanStack Query cache, instead of
every tab polling ``/instances`` independently.

``max_ticks`` bounds the number of emissions so tests can consume a finite
stream; in production it defaults to ``None`` (stream until the client
disconnects).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from brainpalace_dashboard.services.instances import InstanceService

router = APIRouter(prefix="/dashboard/api", tags=["events"])
service = InstanceService()


async def _instance_events(
    poll_s: float, max_ticks: int | None
) -> AsyncIterator[dict[str, Any]]:
    """Yield one ``instances`` SSE event per tick until ``max_ticks`` (if set)."""
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        try:
            data = service.list()
        except Exception:  # never let a transient listing error kill the stream
            data = []
        yield {"event": "instances", "data": json.dumps(data)}
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        await asyncio.sleep(poll_s)


@router.get("/events")
async def events(
    poll_s: float = Query(5.0, ge=0.0),
    max_ticks: int | None = Query(None, ge=1),
) -> EventSourceResponse:
    """Live SSE stream of the fleet ``instances`` list."""
    return EventSourceResponse(_instance_events(poll_s, max_ticks))
