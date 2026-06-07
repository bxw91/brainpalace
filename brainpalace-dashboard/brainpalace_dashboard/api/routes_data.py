"""Per-instance data reads + action proxies.

Each route is a thin wrapper that forwards to the live project server via
``ProxyService`` and normalizes any upstream/transport failure to
``{error, detail, upstream_status}`` (never a blank 500). Upstream paths are the
*live* server routes confirmed against ``/openapi.json`` — note that cache,
folders and jobs live under the ``/index/`` prefix on the server.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body
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


@router.get("/postgres")
async def postgres(id_: str) -> Any:
    return await _call(id_, "GET", "/health/postgres")


@router.get("/folders")
async def folders(id_: str) -> Any:
    return await _call(id_, "GET", "/index/folders/")


@router.get("/jobs")
async def jobs(id_: str) -> Any:
    return await _call(id_, "GET", "/index/jobs/")


@router.get("/jobs/{job_id}")
async def job(id_: str, job_id: str) -> Any:
    return await _call(id_, "GET", f"/index/jobs/{job_id}")


@router.get("/cache")
async def cache(id_: str) -> Any:
    return await _call(id_, "GET", "/index/cache/")


@router.get("/graph")
async def graph(id_: str) -> Any:
    # graph stats live inside /health/status; expose a focused view client-side.
    return await _call(id_, "GET", "/health/status")


@router.get("/memories")
async def memories(id_: str) -> Any:
    return await _call(id_, "GET", "/memories/")


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


@router.post("/git/reindex")
async def git_reindex(id_: str) -> Any:
    return await _call(id_, "POST", "/git/reindex")


@router.post("/sessions/reindex")
async def sessions_reindex(id_: str) -> Any:
    return await _call(id_, "POST", "/sessions/reindex")


@router.post("/memories/{memory_id}/obsolete")
async def memory_obsolete(id_: str, memory_id: str) -> Any:
    return await _call(id_, "POST", f"/memories/{memory_id}/obsolete")


@router.delete("/memories/{memory_id}")
async def memory_delete(id_: str, memory_id: str) -> Any:
    return await _call(id_, "DELETE", f"/memories/{memory_id}")


@router.post("/memories/rebuild")
async def memory_rebuild(id_: str) -> Any:
    return await _call(id_, "POST", "/memories/rebuild")
