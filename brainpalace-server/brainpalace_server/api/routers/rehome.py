# brainpalace_server/api/routers/rehome.py
"""Rehome status + resume endpoints (spec A8). Allowlisted under quarantine (D4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from brainpalace_server.rehome.orchestrator import (
    RehomeLockBusy,
    RehomeRefused,
    resume_rehome,
)
from brainpalace_server.rehome.quarantine import (
    QuarantineState,
    start_frozen_mutators,
)

router = APIRouter(tags=["Rehome"])


def _quarantine(request: Request) -> QuarantineState:
    q = getattr(request.app.state, "rehome_quarantine", None)
    if not isinstance(q, QuarantineState):
        return QuarantineState(active=False)
    return q


@router.get("/")
async def rehome_status(request: Request) -> dict[str, Any]:
    """Current rehome/quarantine status (always served, even when quarantined)."""
    q = _quarantine(request)
    return {
        "quarantined": q.active,
        "status": q.status,
        "reason": q.reason,
    }


@router.post("/resume")
async def rehome_resume(request: Request) -> dict[str, Any]:
    """Resume a pending/failed rehome from its checkpoint (A8).

    On completion the quarantine flag clears so reads work again. Background
    mutators (watcher/job worker) are NOT (re)started mid-process — a server
    restart is recommended to resume live indexing.
    """
    q = _quarantine(request)
    if not q.active:
        raise HTTPException(status_code=409, detail="no pending rehome to resume")

    stores = getattr(request.app.state, "rehome_stores", None)
    state_dir = getattr(request.app.state, "state_dir_str", None)
    project_root = getattr(request.app.state, "project_root", None)
    if stores is None or not state_dir:
        raise HTTPException(status_code=503, detail="rehome stores unavailable")

    try:
        result = await resume_rehome(
            Path(state_dir), Path(project_root or state_dir), stores=stores
        )
    except RehomeLockBusy as exc:
        raise HTTPException(status_code=409, detail=f"rehome locked: {exc}") from exc
    except RehomeRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.status == "done":
        request.app.state.rehome_quarantine = QuarantineState(active=False)
        # Start the background mutators frozen under quarantine (D11) so live
        # indexing resumes in-process, without needing a server restart.
        started = await start_frozen_mutators(request.app.state)
        return {
            "quarantined": False,
            "status": "done",
            "resumed_workers": started,
            "note": (
                "rehome complete; live indexing resumed"
                if started
                else "rehome complete"
            ),
        }
    request.app.state.rehome_quarantine = QuarantineState(
        active=True, reason=result.error, status=result.status
    )
    return {"quarantined": True, "status": result.status, "reason": result.error}
