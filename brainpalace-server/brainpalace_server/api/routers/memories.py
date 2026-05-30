"""Curated memory namespace endpoints (Phase 030).

CRUD over the markdown-backed memory store plus a memory-only recall. The
markdown file is the source of truth; these endpoints mutate it and sync the
Chroma shadow index (ADR 0001).
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from brainpalace_server.models.memory import (
    MemoryCreate,
    MemoryListResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    MemoryResponse,
)
from brainpalace_server.services.memory_service import (
    MemoryCapError,
    MemoryDuplicateError,
    MemoryNotFoundError,
    MemoryService,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _service(request: Request) -> MemoryService:
    ms: MemoryService | None = getattr(request.app.state, "memory_service", None)
    if ms is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory namespace is disabled (MEMORY_ENABLED=false).",
        )
    return ms


@router.post(
    "/",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a memory",
)
async def create_memory(body: MemoryCreate, request: Request) -> MemoryResponse:
    ms = _service(request)
    try:
        mem = await ms.add(
            text=body.text,
            section=body.section,
            tags=body.tags,
            origin=body.origin,
            confidence=body.confidence,
        )
    except MemoryDuplicateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except MemoryCapError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e)
        ) from e
    return MemoryResponse(memory=mem, message="saved")


@router.get(
    "/",
    response_model=MemoryListResponse,
    summary="List memories",
)
async def list_memories(
    request: Request,
    tag: str | None = None,
    section: str | None = None,
    include_obsolete: bool = False,
) -> MemoryListResponse:
    ms = _service(request)
    memories = ms.load()
    if not include_obsolete:
        memories = [m for m in memories if m.is_active]
    if tag:
        memories = [m for m in memories if tag in m.tags]
    if section:
        memories = [m for m in memories if m.section == section]
    return MemoryListResponse(
        memories=memories,
        total=len(memories),
        char_count=ms.char_count(),
        char_cap=ms.char_cap,
    )


@router.post(
    "/recall",
    response_model=MemoryRecallResponse,
    summary="Recall from the memory namespace only",
)
async def recall_memories(
    body: MemoryRecallRequest, request: Request
) -> MemoryRecallResponse:
    ms = _service(request)
    hits, took = await ms.recall(
        body.query, top_k=body.top_k, similarity_threshold=body.similarity_threshold
    )
    return MemoryRecallResponse(hits=hits, total=len(hits), query_time_ms=took)


@router.delete(
    "/{memory_id}",
    summary="Delete a memory",
)
async def delete_memory(memory_id: str, request: Request) -> dict[str, str]:
    ms = _service(request)
    try:
        await ms.delete(memory_id)
    except MemoryNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown memory {memory_id}"
        ) from e
    return {"status": "deleted", "id": memory_id}


@router.post(
    "/{memory_id}/obsolete",
    response_model=MemoryResponse,
    summary="Mark a memory obsolete",
)
async def obsolete_memory(
    memory_id: str, request: Request, superseded_by: str | None = None
) -> MemoryResponse:
    ms = _service(request)
    try:
        mem = await ms.obsolete(memory_id, superseded_by=superseded_by)
    except MemoryNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown memory {memory_id}"
        ) from e
    return MemoryResponse(memory=mem, message="obsoleted")


@router.post(
    "/rebuild",
    summary="Rebuild the memory shadow index from the markdown (ADR 0001)",
)
async def rebuild_memories(request: Request) -> dict[str, int | str]:
    ms = _service(request)
    n = await ms.rebuild_from_markdown()
    return {"status": "rebuilt", "entries": n}
