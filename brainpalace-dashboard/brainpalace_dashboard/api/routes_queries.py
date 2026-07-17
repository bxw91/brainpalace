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

#: Scope filters a replay forwards, mirroring exactly the keys the project
#: server records into ``filters_json`` (see ``api/routers/query.py``). All are
#: result-*scoping* filters — none reveals sensitive content. The sensitivity
#: gate is intentionally absent: this is a shared surface and must never proxy
#: it (frozen by ``test_replay_omits_sensitive``).
_REPLAY_SCOPE_FILTERS = (
    "source_types",
    "languages",
    "file_paths",
    "domains",
    "metadata_filter",
    "entity_types",
    "relationship_types",
)


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


@router.get("/stats")
async def stats(id_: str, since: float | None = None, top_n: int = 10) -> Any:
    params = {
        k: v for k, v in {"since": since, "top_n": top_n}.items() if v is not None
    }
    return await _call(id_, "GET", "/query/stats", params=params)


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
    for key in ("alpha", "rerank"):
        if key in body:
            payload[key] = body[key]
    # A18 — a replay must re-run the SAME query, so the logged scope filters have
    # to be forwarded (dropping them silently re-runs a broader query). They come
    # back nested under `filters`. This is a SHARED surface, so the forward is an
    # explicit scope-filter allowlist — mirroring exactly the keys the project
    # server logs into `filters_json` — NOT a blind spread of the client-supplied
    # `filters` dict: the sensitivity gate is deliberately never proxied here
    # (see test_replay_omits_sensitive), and a wholesale spread of a POST body
    # could smuggle it back in.
    filters = body.get("filters")
    if isinstance(filters, dict):
        for key in _REPLAY_SCOPE_FILTERS:
            value = filters.get(key)
            if value:
                payload[key] = value
    return await _call(id_, "POST", "/query/", json=payload)
