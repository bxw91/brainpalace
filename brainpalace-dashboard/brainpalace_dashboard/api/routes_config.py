"""Config schema + per-instance config GET/PATCH (batched, all-or-nothing)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from brainpalace_dashboard.services.config_svc import ConfigService, ConfigWriteError
from brainpalace_dashboard.services.instances import (
    InstanceNotFound,
    InstanceService,
)

router = APIRouter(prefix="/dashboard/api", tags=["config"])
config_service = ConfigService()
instance_service = InstanceService()


def _state_dir_for(id_: str) -> Path:
    entry = instance_service._resolve(id_)  # raises InstanceNotFound
    root = Path(entry["project_root"])
    return Path(entry["state_dir"]) if entry.get("state_dir") else root / ".brainpalace"


class ConfigPatch(BaseModel):
    values: dict[str, Any]
    restart: bool = False


@router.get("/schema")
def get_schema() -> dict[str, Any]:
    return config_service.schema()


@router.get("/instances/{id_}/config")
def get_config(id_: str) -> dict[str, Any]:
    try:
        return config_service.read(_state_dir_for(id_))
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None


@router.patch("/instances/{id_}/config")
def patch_config(id_: str, body: ConfigPatch) -> Any:
    try:
        state_dir = _state_dir_for(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None
    try:
        config_service.write(state_dir, body.values)
    except ConfigWriteError as e:
        # Body is exactly {"errors": [...]} so the client reads .errors directly.
        return JSONResponse(status_code=422, content={"errors": e.errors})
    restarted = False
    if body.restart:
        try:
            instance_service.restart(id_)
            restarted = True
        except Exception as e:  # surface but don't lose the saved config
            return {"ok": True, "restarted": False, "restart_error": str(e)}
    return {"ok": True, "restarted": restarted}
