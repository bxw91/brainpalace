"""Knowledge-graph browse endpoints (dashboard graph browser)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import get_graph_store_manager

router = APIRouter()


def _require_graph_enabled() -> None:
    if not settings.ENABLE_GRAPH_INDEX:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph indexing is disabled (set graph_indexing.enabled: true "
            "in config.yaml, and ENABLE_GRAPH_INDEX is not false).",
        )


@router.get(
    "/nodes",
    summary="Search graph nodes",
    description="Name-substring entity search with active-edge degree; the "
    "seed picker for the dashboard graph browser. 503 when graph indexing "
    "is disabled.",
)
async def search_nodes(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _require_graph_enabled()
    mgr = get_graph_store_manager()
    return {"nodes": mgr.search_nodes(q, limit=limit)}


@router.get(
    "/top",
    summary="Highest-degree hub nodes",
    description="Most-connected entities (active-edge degree), no search "
    "needed — seeds the dashboard graph browser on open. 503 when graph "
    "indexing is disabled.",
)
async def top_nodes(
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _require_graph_enabled()
    mgr = get_graph_store_manager()
    return {"nodes": mgr.top_nodes(limit=limit)}


@router.get(
    "/neighbors",
    summary="Expand one node's neighborhood",
    description="Active edges touching the node plus every connected node — "
    "one expand step of the seed/expand browser. 503 when graph indexing "
    "is disabled.",
)
async def neighbors(
    node: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    _require_graph_enabled()
    mgr = get_graph_store_manager()
    return mgr.neighbors([node], limit=limit)
