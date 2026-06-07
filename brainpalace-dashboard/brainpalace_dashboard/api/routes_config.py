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
from brainpalace_dashboard.services.runtime_config_svc import (
    RuntimeConfigError,
    RuntimeConfigService,
)

router = APIRouter(prefix="/dashboard/api", tags=["config"])
config_service = ConfigService()
instance_service = InstanceService()
runtime_config_service = RuntimeConfigService()


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


@router.get("/instances/{id_}/config/effective")
def get_config_effective(id_: str) -> dict[str, Any]:
    """Per-key effective value + provenance (project > global > code default).

    Powers the form's "inherited from global / default" hints and the
    empty-when-unset behavior — the editable value still comes from GET /config.
    """
    try:
        return config_service.effective(_state_dir_for(id_))
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


# --------------------------------------------------------------------------- #
# Global config — the machine-wide XDG config.yaml (every project inherits).
# This IS the global layer, so no effective/provenance resolution: the form
# renders the schema + the file's own (masked) values directly.
# --------------------------------------------------------------------------- #
@router.get("/global-config")
def get_global_config() -> dict[str, Any]:
    return config_service.read_global()


@router.patch("/global-config", response_model=None)
def patch_global_config(body: ConfigPatch) -> Any:
    try:
        config_service.write_global(body.values)
    except ConfigWriteError as e:
        return JSONResponse(status_code=422, content={"errors": e.errors})
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Per-project runtime bind — config.json (bind_host / port range / auto_port).
# Read by the CLI at server start; changes need a RESTART to take effect.
# --------------------------------------------------------------------------- #
@router.get("/instances/{id_}/runtime-config")
def get_runtime_config(id_: str) -> dict[str, Any]:
    try:
        return runtime_config_service.read(_state_dir_for(id_))
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None


@router.patch("/instances/{id_}/runtime-config", response_model=None)
def patch_runtime_config(id_: str, body: ConfigPatch) -> Any:
    try:
        state_dir = _state_dir_for(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None
    try:
        runtime_config_service.write(state_dir, body.values)
    except RuntimeConfigError as e:
        return JSONResponse(status_code=422, content={"errors": e.errors})
    restarted = False
    if body.restart:
        try:
            instance_service.restart(id_)
            restarted = True
        except Exception as e:  # surface but don't lose the saved config
            return {"ok": True, "restarted": False, "restart_error": str(e)}
    # Bind changes only apply on restart — flag it so the UI can prompt.
    return {"ok": True, "restarted": restarted, "restart_required": not restarted}
