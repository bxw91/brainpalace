"""Control-plane (dashboard "server") settings — distinct from per-instance config.

The dashboard's own settings (`dashboard:` block in the XDG config.yaml:
host/port/poll_s/token) are fleet-wide and govern the control-plane process
itself, not any single project server. The per-instance Config tab edits each
project's `config.yaml`; this surface edits the dashboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from brainpalace_dashboard import __version__
from brainpalace_dashboard.config import (
    TOKEN_MASK,
    DashboardConfigError,
    load_dashboard_config,
    save_dashboard_config,
)
from brainpalace_dashboard.server import read_dashboard_runtime

router = APIRouter(prefix="/dashboard/api/settings", tags=["settings"])

# Fields that only take effect when the dashboard process is restarted.
RESTART_FIELDS = {"host", "port", "token"}


@router.get("")
def get_settings() -> dict[str, Any]:
    cfg = load_dashboard_config()
    runtime = read_dashboard_runtime() or {}
    return {
        "host": cfg.host,
        "port": cfg.port,
        "poll_s": cfg.poll_s,
        "autostart": cfg.autostart,
        # Never expose the real token; the SPA only learns whether one is set and
        # echoes back the mask to keep it unchanged.
        "token_set": cfg.token is not None,
        "token": TOKEN_MASK if cfg.token is not None else "",
        "version": __version__,
        "runtime": {
            "running": bool(runtime.get("pid")),
            "port": runtime.get("port"),
            "base_url": runtime.get("base_url"),
        },
    }


class SettingsPatch(BaseModel):
    host: str | None = None
    port: int | None = None
    poll_s: int | None = None
    token: str | None = None
    autostart: bool | None = None


@router.patch("", response_model=None)
def patch_settings(body: SettingsPatch) -> dict[str, Any] | JSONResponse:
    current = load_dashboard_config()
    values = body.model_dump(exclude_unset=True)

    # Which submitted fields actually change a restart-sensitive setting?
    restart_required: list[str] = []
    if "host" in values and values["host"] != current.host:
        restart_required.append("host")
    if "port" in values and values["port"] != current.port:
        restart_required.append("port")
    if "token" in values and values["token"] != TOKEN_MASK:
        new = values["token"] or None
        if new != current.token:
            restart_required.append("token")

    try:
        save_dashboard_config(values)
    except DashboardConfigError as e:
        return JSONResponse(status_code=422, content={"errors": e.errors})
    return {"ok": True, "restart_required": restart_required}
