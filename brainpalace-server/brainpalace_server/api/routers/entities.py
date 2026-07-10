"""Identity API (G5 / spec ``.planning/specs/2026-07-09-g5-identity-store.md``):
person / alias / link over the engine's ``IdentityStore``. The engine stores
and *ranks* candidates; it NEVER picks a winner (D7) — the consumer app decides.

Store access mirrors ``routers/ingest.py::_get_service``: read the None-safe
``app.state.identity_store`` and 503 when it is absent (identity failed to
initialize, e.g. no writable state dir)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from brainpalace_server.storage.identity_store import Alias, Link, Person

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_store(request: Request) -> Any:
    store = getattr(request.app.state, "identity_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Identity store is not available (no writable state "
            "directory?). Check the server logs.",
        )
    return store


@router.post("/person", summary="Upsert a person (also the EmittedEntity sink)")
async def upsert_person(person: Person, request: Request) -> dict[str, Any]:
    store = _get_store(request)
    pid = store.upsert_person(person)
    # G5 D2: one-way projection into the graph when GraphRAG is enabled, so
    # relational traversal works. Best-effort; never blocks the identity write,
    # and identity is never read back out of the graph.
    if getattr(request.app.state, "graphrag_enabled", False):
        try:
            from brainpalace_server.services.identity_projection import (
                project_person,
            )
            from brainpalace_server.storage.graph_store import (
                get_graph_store_manager,
            )

            stored = store.get_person(pid)
            project_person(get_graph_store_manager(), stored)
        except Exception:  # noqa: BLE001 — projection must not fail the write
            logger.exception("person graph projection failed")
    return {"person_id": pid}


@router.post("/alias", summary="Bind a surface to a person (scoped, time-bounded)")
async def upsert_alias(alias: Alias, request: Request) -> dict[str, Any]:
    store = _get_store(request)
    store.upsert_alias(alias)
    return {"ok": True}


@router.post("/link", summary="Attach a ref to a person, or record it unresolved")
async def add_link(link: Link, request: Request) -> dict[str, Any]:
    store = _get_store(request)
    lid = store.add_link(link)
    return {"link_id": lid}


@router.delete("/link/{link_id}", summary="Retract a link (never touches text)")
async def retract_link(link_id: str, request: Request) -> dict[str, Any]:
    store = _get_store(request)
    ok = store.retract_link(link_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"no link {link_id}")
    return {"ok": True}


@router.get("/resolve", summary="Ranked candidates + evidence (never picks)")
async def resolve(
    request: Request,
    surface: str,
    scope: str | None = None,
    at: str | None = None,
    ref: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    store = _get_store(request)
    cands = store.resolve_candidates(
        surface, scope=scope, at=at, ref=ref, session_id=session_id
    )
    return {"candidates": cands}


@router.get("/unresolved", summary="The unresolved-link bucket")
async def unresolved(request: Request) -> dict[str, Any]:
    store = _get_store(request)
    links = [link.model_dump() for link in store.unresolved()]
    return {"links": links}


@router.post("/backfill", summary="Re-score unresolved links against current aliases")
async def backfill(request: Request) -> dict[str, Any]:
    store = _get_store(request)
    n = store.backfill()
    return {"rescored": n}
