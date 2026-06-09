"""Config schema + per-instance config GET/PATCH (batched, all-or-nothing)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from brainpalace_dashboard.services.config_svc import (
    ConfigService,
    ConfigWriteError,
    _changed_dotpaths,
)
from brainpalace_dashboard.services.data_guard import breaking_changes, build_conflict
from brainpalace_dashboard.services.instances import (
    InstanceNotFound,
    InstanceService,
)
from brainpalace_dashboard.services.proxy import ProxyService
from brainpalace_dashboard.services.runtime_config_svc import (
    RuntimeConfigError,
    RuntimeConfigService,
)

router = APIRouter(prefix="/dashboard/api", tags=["config"])
config_service = ConfigService()
instance_service = InstanceService()
runtime_config_service = RuntimeConfigService()
proxy_service = ProxyService()


def _state_dir_for(id_: str) -> Path:
    entry = instance_service._resolve(id_)  # raises InstanceNotFound
    root = Path(entry["project_root"])
    return Path(entry["state_dir"]) if entry.get("state_dir") else root / ".brainpalace"


def _read_existing(state_dir: Path) -> dict[str, Any]:
    path = Path(state_dir) / "config.yaml"
    loaded = yaml.safe_load(path.read_text()) if path.exists() else {}
    return loaded if isinstance(loaded, dict) else {}


def _run_proxy(coro: Any) -> Any:
    """Run one proxy coroutine in a fresh event loop, closing the client after.

    Routes are sync; each call gets its own loop. ``aclose()`` resets the shared
    httpx client so it is never reused across a closed loop.
    """

    async def _runner() -> Any:
        try:
            return await coro
        finally:
            await proxy_service.aclose()

    return asyncio.run(_runner())


def _changed_field_errors(
    values: dict[str, Any], changed: set[str]
) -> list[dict[str, Any]]:
    """Validation errors confined to the fields this save actually changes."""
    return [e for e in config_service.validate(values) if e["field"] in changed]


def _data_conflict(
    id_: str, existing: dict[str, Any], values: dict[str, Any], changed: set[str]
) -> dict[str, Any] | None:
    """Return a 409 conflict payload if the save breaks existing data, else None.

    The form submits the full draft, so the changed dotpaths are exactly the
    leaves of ``values`` that differ from the on-disk config.
    """
    breaking = breaking_changes(changed)
    if not breaking:
        return None
    fingerprint = _run_proxy(proxy_service.fetch_fingerprint(id_))
    if not fingerprint or not fingerprint.get("has_data"):
        return None  # nothing indexed, or server down → don't block
    return build_conflict(breaking, values, existing, fingerprint)


class ConfigPatch(BaseModel):
    values: dict[str, Any]
    restart: bool = False
    force_reindex: bool = False


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


class ConfigUnset(BaseModel):
    """Keys to remove from the project config so they inherit global/code."""

    dotpaths: list[str]


@router.post("/instances/{id_}/config/unset")
def unset_config(id_: str, body: ConfigUnset) -> Any:
    """Remove project-level keys so they inherit from global / code default.

    Returns ``{"removed": [...], "effective": {dotpath: {value, source}}}`` with
    the NEW resolved value + source per requested key, so the form can update the
    field in place to its inherited value without a full refetch.
    """
    try:
        state_dir = _state_dir_for(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None
    return config_service.unset(state_dir, body.dotpaths)


@router.patch("/instances/{id_}/config")
def patch_config(id_: str, body: ConfigPatch) -> Any:
    try:
        state_dir = _state_dir_for(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found") from None

    existing = _read_existing(state_dir)
    changed = _changed_dotpaths(body.values, existing)

    # Invalid edits take precedence over the data guard (422 before 409).
    errors = _changed_field_errors(body.values, changed)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    # Data-compatibility guard: block changes that would invalidate/strand the
    # existing index (unless the user opted into Save & reindex).
    if not body.force_reindex:
        conflict = _data_conflict(id_, existing, body.values, changed)
        if conflict is not None:
            return JSONResponse(status_code=409, content=conflict)

    try:
        config_service.write(state_dir, body.values)
    except ConfigWriteError as e:
        # Body is exactly {"errors": [...]} so the client reads .errors directly.
        return JSONResponse(status_code=422, content={"errors": e.errors})

    out: dict[str, Any] = {"ok": True}
    if body.force_reindex:
        try:
            out["reindex_triggered"] = _run_proxy(
                proxy_service.trigger_full_reindex(id_)
            )
        except Exception as e:  # save persisted; surface reindex failure
            return {"ok": True, "reindex_triggered": 0, "reindex_error": str(e)}

    restarted = False
    if body.restart:
        try:
            instance_service.restart(id_)
            restarted = True
        except Exception as e:  # surface but don't lose the saved config
            return {"ok": True, "restarted": False, "restart_error": str(e)}
    out["restarted"] = restarted
    return out


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
    existing_global = _read_existing(Path(config_service._global_config_path()).parent)
    global_changed = _changed_dotpaths(body.values, existing_global)

    # Invalid edits take precedence over the data guard (422 before 409).
    errors = _changed_field_errors(body.values, global_changed)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    # Guard the global save against every running instance that inherits it:
    # block if any has indexed data a breaking change would invalidate.
    if not body.force_reindex:
        for row in instance_service.list():
            if not row.get("base_url"):
                continue
            sd = (
                Path(row["state_dir"])
                if row.get("state_dir")
                else Path(row["project_root"]) / ".brainpalace"
            )
            existing = _read_existing(sd)
            changed = _changed_dotpaths(body.values, existing)
            conflict = _data_conflict(row["id"], existing, body.values, changed)
            if conflict is not None:
                return JSONResponse(status_code=409, content=conflict)
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
