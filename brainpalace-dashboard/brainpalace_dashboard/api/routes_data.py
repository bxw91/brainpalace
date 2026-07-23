"""Per-instance data reads + action proxies.

Each route is a thin wrapper that forwards to the live project server via
``ProxyService`` and normalizes any upstream/transport failure to
``{error, detail, upstream_status}`` (never a blank 500). Upstream paths are the
*live* server routes confirmed against ``/openapi.json`` — note that cache,
folders and jobs live under the ``/index/`` prefix on the server.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from brainpalace_dashboard.services.capabilities import parse_openapi
from brainpalace_dashboard.services.proxy import ProxyService, UpstreamError

router = APIRouter(prefix="/dashboard/api/instances/{id_}", tags=["data"])
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


# ---- reads ----
@router.get("/health")
async def health(id_: str) -> Any:
    """Liveness + server version/mode (the project server's ``GET /health/``)."""
    return await _call(id_, "GET", "/health/")


@router.get("/status")
async def status(id_: str) -> Any:
    return await _call(id_, "GET", "/health/status")


@router.get("/providers")
async def providers(id_: str) -> Any:
    return await _call(id_, "GET", "/health/providers")


@router.get("/metrics/usage")
async def metrics_usage(id_: str, window: str = "24h") -> Any:
    """Windowed usage/spend telemetry (the server's ``GET /metrics/usage``)."""
    return await _call(id_, "GET", "/metrics/usage", params={"window": window})


@router.get("/postgres")
async def postgres(id_: str) -> Any:
    return await _call(id_, "GET", "/health/postgres")


@router.get("/folders")
async def folders(id_: str) -> Any:
    return await _call(id_, "GET", "/index/folders/")


@router.get("/jobs")
async def jobs(id_: str, all_: bool = Query(False, alias="all")) -> Any:
    """Job queue listing. ``?all=1`` reveals no-op completed jobs
    (status=done, no chunk delta, no error) that are hidden by default
    (Fix 4)."""
    params = {"all": 1} if all_ else None
    return await _call(id_, "GET", "/index/jobs/", params=params)


@router.get("/jobs/{job_id}")
async def job(id_: str, job_id: str) -> Any:
    return await _call(id_, "GET", f"/index/jobs/{job_id}")


@router.get("/cache")
async def cache(id_: str) -> Any:
    return await _call(id_, "GET", "/index/cache/")


@router.get("/cache/history")
async def cache_history(id_: str, since: float | None = None) -> Any:
    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    return await _call(id_, "GET", "/index/cache/history", params=params)


@router.get("/cache/economics")
async def cache_economics(id_: str, avg_tokens: int = 400) -> Any:
    return await _call(
        id_, "GET", "/index/cache/economics", params={"avg_tokens": avg_tokens}
    )


@router.get("/documents")
async def documents(
    id_: str,
    folder: str,
    contains: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> Any:
    params: dict[str, Any] = {"folder": folder, "limit": limit, "offset": offset}
    if contains:
        params["contains"] = contains
    return await _call(id_, "GET", "/index/documents", params=params)


@router.get("/documents/chunks")
async def document_chunks(id_: str, folder: str, path: str, limit: int = 50) -> Any:
    return await _call(
        id_,
        "GET",
        "/index/documents/chunks",
        params={"folder": folder, "path": path, "limit": limit},
    )


@router.get("/ingest/sources")
async def ingest_sources(
    id_: str,
    domain: str | None = None,
    source: str | None = None,
    include_sensitive: bool = False,
) -> Any:
    params: dict[str, Any] = {"include_sensitive": include_sensitive}
    if domain:
        params["domain"] = domain
    if source:
        params["source"] = source
    return await _call(id_, "GET", "/ingest/sources", params=params)


@router.get("/ingest/chunks")
async def ingest_chunks(
    id_: str,
    source_id: str,
    offset: int = 0,
    limit: int = 50,
    include_sensitive: bool = False,
) -> Any:
    return await _call(
        id_,
        "GET",
        f"/ingest/text/{source_id}",
        params={
            "offset": offset,
            "limit": limit,
            "include_sensitive": include_sensitive,
        },
    )


@router.delete("/ingest/source/{source_id}")
async def ingest_forget(id_: str, source_id: str) -> Any:
    # Full forget: cascade-delete a source_id across chunks + records +
    # references (the server's `/ingest/source/{id}` = `ingest --forget`), so a
    # dashboard delete leaves no leftover tier behind.
    return await _call(id_, "DELETE", f"/ingest/source/{source_id}")


@router.get("/graph")
async def graph(id_: str) -> Any:
    # graph stats live inside /health/status; expose a focused view client-side.
    return await _call(id_, "GET", "/health/status")


@router.get("/graph/nodes")
async def graph_nodes(
    id_: str, q: str, limit: int = 20, domains: str | None = None
) -> Any:
    params: dict[str, Any] = {"q": q, "limit": limit}
    if domains:
        params["domains"] = domains
    return await _call(id_, "GET", "/graph/nodes", params=params)


@router.get("/graph/neighbors")
async def graph_neighbors(
    id_: str, node: str, limit: int = 200, domains: str | None = None
) -> Any:
    params: dict[str, Any] = {"node": node, "limit": limit}
    if domains:
        params["domains"] = domains
    return await _call(id_, "GET", "/graph/neighbors", params=params)


@router.get("/graph/top")
async def graph_top(id_: str, limit: int = 20, domains: str | None = None) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if domains:
        params["domains"] = domains
    return await _call(id_, "GET", "/graph/top", params=params)


@router.get("/graph/impact")
async def graph_impact(id_: str, node: str, max_depth: int = 2, limit: int = 30) -> Any:
    return await _call(
        id_,
        "GET",
        "/graph/impact",
        params={"node": node, "max_depth": max_depth, "limit": limit},
    )


@router.get("/graph/cochange")
async def graph_cochange(
    id_: str, node: str, min_shared: int = 2, limit: int = 10
) -> Any:
    return await _call(
        id_,
        "GET",
        "/graph/cochange",
        params={"node": node, "min_shared": min_shared, "limit": limit},
    )


@router.get("/memories")
async def memories(id_: str) -> Any:
    return await _call(id_, "GET", "/memories/")


@router.get("/sessions/archive")
async def sessions_archive(id_: str) -> Any:
    return await _call(id_, "GET", "/sessions/archive")


@router.get("/sessions/decisions")
async def sessions_decisions(
    id_: str, contains: str | None = None, limit: int = 50
) -> Any:
    params: dict[str, Any] = {"limit": limit}
    if contains:
        params["contains"] = contains
    return await _call(id_, "GET", "/sessions/decisions", params=params)


@router.get("/sessions/timeline")
async def sessions_timeline(id_: str, entity: str) -> Any:
    return await _call(id_, "GET", "/sessions/timeline", params={"entity": entity})


@router.get("/runtime")
async def runtime(id_: str) -> Any:
    return await _call(id_, "GET", "/runtime/")


@router.get("/logs")
async def logs(id_: str, lines: int = 200, level: str | None = None) -> Any:
    """Tail the server log file (proxy onto the server's ``/health/logs``)."""
    params: dict[str, Any] = {"lines": lines}
    if level:
        params["level"] = level
    return await _call(id_, "GET", "/health/logs", params=params)


@router.get("/capabilities")
async def capabilities(id_: str) -> Any:
    doc = await _call(id_, "GET", "/openapi.json")
    if isinstance(doc, JSONResponse):
        return doc
    return parse_openapi(doc)


# ---- actions ----
@router.post("/index")
async def add_folder(id_: str, body: Annotated[dict[str, Any], Body(...)]) -> Any:
    return await _call(id_, "POST", "/index/", json=body)


@router.delete("/folders")
async def remove_folder(id_: str, body: Annotated[dict[str, Any], Body(...)]) -> Any:
    # The server contract is {"folder_path": ...}; older frontend builds sent
    # {"path": ...}, which the server rejects with a 422. Normalize so either
    # key works regardless of the bundled frontend asset version.
    if "folder_path" not in body and "path" in body:
        body = {**body, "folder_path": body["path"]}
    return await _call(id_, "DELETE", "/index/folders/", json=body)


@router.delete("/index")
async def reset_index(id_: str) -> Any:
    return await _call(id_, "DELETE", "/index/")


@router.delete("/cache")
async def clear_cache(id_: str) -> Any:
    return await _call(id_, "DELETE", "/index/cache/")


@router.delete("/jobs/{job_id}")
async def cancel_job(id_: str, job_id: str) -> Any:
    return await _call(id_, "DELETE", f"/index/jobs/{job_id}")


@router.post("/jobs/{job_id}/approve")
async def approve_job(id_: str, job_id: str) -> Any:
    return await _call(id_, "POST", f"/index/jobs/{job_id}/approve")


@router.post("/providers/test")
async def providers_test(id_: str) -> Any:
    return await _call(id_, "POST", "/health/providers/test")


@router.post("/graph/rebuild")
async def graph_rebuild(id_: str) -> Any:
    # Rebuild the code graph from already-indexed chunks (no embedding); the
    # server derives the workspace root from its first indexed folder.
    return await _call(id_, "POST", "/index/", json={}, params={"rebuild_graph": True})


@router.post("/git/reindex")
async def git_reindex(id_: str) -> Any:
    return await _call(id_, "POST", "/git/reindex")


@router.post("/sessions/reindex")
async def sessions_reindex(id_: str) -> Any:
    return await _call(id_, "POST", "/sessions/reindex")


@router.post("/memories")
async def memory_create(id_: str, body: Annotated[dict[str, Any], Body(...)]) -> Any:
    return await _call(id_, "POST", "/memories/", json=body)


@router.post("/memories/{memory_id}/obsolete")
async def memory_obsolete(id_: str, memory_id: str) -> Any:
    return await _call(id_, "POST", f"/memories/{memory_id}/obsolete")


@router.delete("/memories/{memory_id}")
async def memory_delete(id_: str, memory_id: str) -> Any:
    return await _call(id_, "DELETE", f"/memories/{memory_id}")


@router.post("/memories/rebuild")
async def memory_rebuild(id_: str) -> Any:
    return await _call(id_, "POST", "/memories/rebuild")
