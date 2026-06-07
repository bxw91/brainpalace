"""Control-plane Queries routes — history list/detail + live replay.

Thin proxies onto the project server's ``/query/history[...]`` reads and a
``/query/`` replay. Every upstream/transport failure is normalized to
``{error, detail, upstream_status}`` (never a blank 500), matching the pattern
in ``routes_data.py``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError

router = APIRouter(prefix="/dashboard/api/instances/{id_}/queries", tags=["queries"])
proxy = ProxyService()


async def _call(
    id_: str,
    method: str,
    path: str,
    json: Any | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        return await proxy.request(id_, method, path, json=json, params=params)
    except UpstreamError as e:
        return JSONResponse(
            status_code=e.upstream_status,
            content={
                "error": "upstream",
                "detail": e.detail,
                "upstream_status": e.upstream_status,
            },
        )


@router.get("")
async def history(
    id_: str,
    since: float | None = None,
    mode: str | None = None,
    contains: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    params = {
        k: v
        for k, v in {
            "since": since,
            "mode": mode,
            "contains": contains,
            "limit": limit,
            "offset": offset,
        }.items()
        if v is not None
    }
    return await _call(id_, "GET", "/query/history", params=params)


@router.get("/{qid}")
async def detail(id_: str, qid: str) -> Any:
    return await _call(id_, "GET", f"/query/history/{qid}")


@router.post("/replay")
async def replay(id_: str, body: Annotated[dict[str, Any], Body(...)]) -> Any:
    payload: dict[str, Any] = {
        "query": body["query"],
        "mode": body.get("mode", "hybrid"),
        "top_k": body.get("top_k", 5),
    }
    if "alpha" in body:
        payload["alpha"] = body["alpha"]
    return await _call(id_, "POST", "/query/", json=payload)
