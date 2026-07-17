"""Tool handlers for the BrainPalace MCP server.

Each handler resolves the target BrainPalace HTTP server via the
existing CWD walk-up (``discover_server_url``), overridable per call
via the optional ``path`` argument — the CWD-coupling mitigation
described in the Phase Q plan. The actual HTTP call is then delegated
to the existing :class:`DocServeClient` so the MCP shim does not own
endpoint shapes, request bodies, or response parsing.

Handlers expose an ``async`` surface (the MCP SDK's ``call_tool`` is
async) but the underlying client is synchronous httpx, so each handler
dispatches its blocking work to a thread via :func:`asyncio.to_thread`.
The returned dicts are JSON-serialisable so the server module can
``json.dumps`` them straight into an MCP ``TextContent`` block.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

from brainpalace_cli.client.api_client import (
    ConnectionError as ABConnectionError,
)
from brainpalace_cli.client.api_client import (
    DocServeClient,
    DocServeError,
    ServerError,
)
from brainpalace_cli.discovery import discover_project_dir, discover_server_url

from ..ai_guidance import render as _render_guidance
from .schemas import (
    AiGuideInput,
    ExtractionFetchInput,
    ExtractionSubmitInput,
    FoldersListInput,
    JobsApproveInput,
    JobsListInput,
    MemorizeInput,
    QueryInput,
    RecallInput,
    SessionContextInput,
    StatusInput,
    WhoamiInput,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_NO_SERVER_MSG = (
    "no brainpalace server running for this project. "
    "Run `brainpalace start` in the project root."
)


def _start_path(path: str | None) -> Path | None:
    """Convert the optional tool-level ``path`` arg into a discovery start."""
    if path is None:
        return None
    return Path(path).expanduser()


def _err(message: str) -> dict[str, Any]:
    """Uniform MCP-side error envelope. Clients see ``{"error": "..."}``."""
    return {"error": message}


def _client_error_to_dict(exc: Exception) -> dict[str, Any]:
    """Map api_client exceptions to MCP-style error dicts."""
    if isinstance(exc, ABConnectionError):
        return _err(f"server unreachable: {exc}")
    if isinstance(exc, ServerError):
        return _err(f"server error {exc.status_code}: {exc.detail or exc}")
    if isinstance(exc, DocServeError):
        return _err(f"client error: {exc}")
    return _err(f"unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Synchronous cores — each tool's actual work
# ---------------------------------------------------------------------------


def _query_sync(inp: QueryInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            resp = client.query(
                query_text=inp.query,
                top_k=inp.top_k,
                mode=inp.mode,
                source_types=inp.source_types,
                languages=inp.languages,
                language=inp.language,
                file_paths=inp.file_paths,
                alpha=inp.alpha,
                similarity_threshold=inp.similarity_threshold,
                entity_types=inp.entity_types,
                relationship_types=inp.relationship_types,
            )
        return dataclasses.asdict(resp)
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _status_sync(inp: StatusInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            health = client.health()
            indexing = client.status()
        return {
            "health": dataclasses.asdict(health),
            "indexing": dataclasses.asdict(indexing),
        }
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _whoami_sync(inp: WhoamiInput) -> dict[str, Any]:
    start = _start_path(inp.file_path)
    project = discover_project_dir(start)
    url = discover_server_url(start)
    if project is None:
        server_status = "no_project"
    elif url is None:
        server_status = "not_running"
    else:
        server_status = "running"
    return {
        "project_root": str(project) if project is not None else None,
        "url": url,
        "server_status": server_status,
    }


def _folders_list_sync(inp: FoldersListInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            folders = client.list_folders()
        return {"folders": [dataclasses.asdict(f) for f in folders]}
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _jobs_list_sync(inp: JobsListInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            jobs = client.list_jobs(limit=inp.limit)
        return {"jobs": jobs}
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _jobs_approve_sync(inp: JobsApproveInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.approve_job(inp.job_id)
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _memorize_sync(inp: MemorizeInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.remember(text=inp.text, section=inp.section, tags=inp.tags)
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _recall_sync(inp: RecallInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.recall(inp.query, top_k=inp.top_k)
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


def _session_context_sync(inp: SessionContextInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.session_context()
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


# ---------------------------------------------------------------------------
# Async surface — what the MCP SDK calls
# ---------------------------------------------------------------------------


async def query_tool(inp: QueryInput) -> dict[str, Any]:
    return await asyncio.to_thread(_query_sync, inp)


async def status_tool(inp: StatusInput) -> dict[str, Any]:
    return await asyncio.to_thread(_status_sync, inp)


async def whoami_tool(inp: WhoamiInput) -> dict[str, Any]:
    # Discovery is pure filesystem + a tiny health check; no need for a thread.
    return _whoami_sync(inp)


async def folders_list_tool(inp: FoldersListInput) -> dict[str, Any]:
    return await asyncio.to_thread(_folders_list_sync, inp)


async def jobs_list_tool(inp: JobsListInput) -> dict[str, Any]:
    return await asyncio.to_thread(_jobs_list_sync, inp)


async def jobs_approve_tool(inp: JobsApproveInput) -> dict[str, Any]:
    return await asyncio.to_thread(_jobs_approve_sync, inp)


async def memorize_tool(inp: MemorizeInput) -> dict[str, Any]:
    return await asyncio.to_thread(_memorize_sync, inp)


async def recall_tool(inp: RecallInput) -> dict[str, Any]:
    return await asyncio.to_thread(_recall_sync, inp)


async def session_context_tool(inp: SessionContextInput) -> dict[str, Any]:
    return await asyncio.to_thread(_session_context_sync, inp)


def _extraction_fetch_sync(inp: ExtractionFetchInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.get_extraction_text(inp.chunk_id)
    except Exception as exc:  # noqa: BLE001 — 404 → no-op signal to the agent
        return _client_error_to_dict(exc)


def _extraction_submit_sync(inp: ExtractionSubmitInput) -> dict[str, Any]:
    url = discover_server_url(_start_path(inp.path))
    if url is None:
        return _err(_NO_SERVER_MSG)
    try:
        with DocServeClient(base_url=url) as client:
            return client.submit_extraction(inp.payload)
    except Exception as exc:  # noqa: BLE001
        return _client_error_to_dict(exc)


async def extraction_fetch_tool(inp: ExtractionFetchInput) -> dict[str, Any]:
    return await asyncio.to_thread(_extraction_fetch_sync, inp)


async def extraction_submit_tool(inp: ExtractionSubmitInput) -> dict[str, Any]:
    return await asyncio.to_thread(_extraction_submit_sync, inp)


async def ai_guide_tool(inp: AiGuideInput) -> dict[str, Any]:
    # Pure local read of the bundled single-source guidance; no server needed.
    # The pull path for MCP-only clients (CLI `ai-guide` is unreachable over MCP).
    text = _render_guidance(tier=inp.tier, fmt="markdown")
    if not text:
        return _err("guidance unavailable")
    return {"tier": inp.tier, "guidance": text}
