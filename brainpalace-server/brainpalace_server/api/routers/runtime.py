"""Runtime introspection endpoint.

Exposes the project this server instance is bound to so a CLI can verify it
is talking to the correct server before issuing commands (recycled-PID
safety). See plan B8.
"""

import os

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from brainpalace_server import __version__

router = APIRouter()


class RuntimeInfo(BaseModel):
    """Identity of the running server instance."""

    project_root: str = Field(
        description="Absolute path of the project this server serves",
    )
    version: str = Field(description="brainpalace-server version")
    pid: int = Field(description="Process ID of the running server")
    started_at: str = Field(
        description="Server start time (ISO 8601); empty if unavailable",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "project_root": "/home/dev/projects/my-app",
                    "version": "9.6.0",
                    "pid": 12345,
                    "started_at": "2026-05-20T19:48:21.477000+00:00",
                }
            ]
        }
    }


@router.get(
    "/",
    response_model=RuntimeInfo,
    summary="Runtime Info",
    description=(
        "Returns the project this server instance is bound to, plus version, "
        "PID and start time. Used by the CLI to confirm a discovered server "
        "actually serves the caller's project (recycled-PID safety)."
    ),
)
async def get_runtime(request: Request) -> RuntimeInfo:
    """Return the identity of this server instance.

    Never blocks. ``project_root`` and ``started_at`` are empty strings if the
    lifespan has not populated ``app.state`` yet.

    Args:
        request: Incoming request (used to read ``app.state``).

    Returns:
        RuntimeInfo with project_root, version, pid and started_at.
    """
    return RuntimeInfo(
        project_root=getattr(request.app.state, "project_root", "") or "",
        version=__version__,
        pid=os.getpid(),
        started_at=getattr(request.app.state, "started_at", "") or "",
    )
