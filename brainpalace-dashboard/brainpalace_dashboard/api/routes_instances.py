"""Instance lifecycle endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from brainpalace_dashboard.services.instances import InstanceNotFound, InstanceService

router = APIRouter(prefix="/dashboard/api/instances", tags=["instances"])
service = InstanceService()


class RegisterBody(BaseModel):
    path: str


@router.get("")
def list_instances() -> list[dict[str, Any]]:
    return service.list()


@router.post("/register")
def register_instance(body: RegisterBody) -> dict[str, Any]:
    """Add an existing project dir to the dashboard list."""
    return service.register(body.path)


@router.get("/{id_}")
def get_instance(id_: str) -> dict[str, Any]:
    for row in service.list():
        if row["id"] == id_:
            return row
    raise HTTPException(status_code=404, detail="instance not found")


@router.post("/{id_}/start")
def start_instance(id_: str) -> dict[str, Any]:
    try:
        return service.start(id_)
    except InstanceNotFound as exc:
        raise HTTPException(status_code=404, detail="instance not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{id_}/stop")
def stop_instance(id_: str, force: bool = Query(False)) -> dict[str, Any]:
    try:
        return service.stop(id_, force=force)
    except InstanceNotFound as exc:
        raise HTTPException(status_code=404, detail="instance not found") from exc


@router.post("/{id_}/restart")
def restart_instance(id_: str) -> dict[str, Any]:
    try:
        return service.restart(id_)
    except InstanceNotFound as exc:
        raise HTTPException(status_code=404, detail="instance not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/{id_}")
def forget_instance(id_: str) -> dict[str, Any]:
    """Remove a project from the dashboard list. Does not delete anything on disk."""
    return service.forget(id_)
