"""FastAPI application factory for the control-plane dashboard."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from brainpalace_dashboard import __version__
from brainpalace_dashboard.api import (
    routes_config,
    routes_data,
    routes_events,
    routes_instances,
    routes_queries,
    routes_settings,
)
from brainpalace_dashboard.config import load_dashboard_config


def _static_dir() -> Path:
    """Directory holding the built SPA (``index.html`` + ``assets/``).

    Overridable via ``BRAINPALACE_DASHBOARD_STATIC`` (used by tests and by
    deployments that ship the build separately). Defaults to the package-local
    ``static/`` directory populated by ``npm run build``.
    """
    override = os.environ.get("BRAINPALACE_DASHBOARD_STATIC")
    if override:
        return Path(override)
    return Path(__file__).parent / "static"


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA under ``/dashboard/`` with client-side-routing
    fallback.

    Registered AFTER the API routers so that the ``/dashboard/{path:path}``
    catch-all never shadows ``/dashboard/api/...`` endpoints. If no build is
    present (e.g. a source checkout without ``npm run build``) this is a no-op,
    leaving the API fully functional.
    """
    static = _static_dir()
    if not (static / "index.html").exists():
        return

    assets = static / "assets"
    if assets.is_dir():
        app.mount(
            "/dashboard/assets",
            StaticFiles(directory=assets),
            name="dashboard-assets",
        )

    @app.get("/dashboard/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (static / path).resolve()
        # Guard against path traversal escaping the static root.
        if path and static.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static / "index.html")


#: API paths exempt from the bearer-token guard even when a token is set.
_AUTH_EXEMPT_PATHS = frozenset({"/dashboard/api/health"})


def _resolve_token() -> str | None:
    """Resolve the configured dashboard token.

    Precedence: the ``BRAINPALACE_DASHBOARD_TOKEN`` env var, then the
    ``dashboard.token`` config value. Returns ``None`` when no token is set
    (meaning the dashboard is unguarded — the default for localhost use).
    """
    env_token = os.environ.get("BRAINPALACE_DASHBOARD_TOKEN")
    if env_token:
        return env_token
    return load_dashboard_config().token


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Guard ``/dashboard/api/**`` with a static bearer token when configured.

    Only API paths are guarded; static/SPA routes and ``/dashboard/api/health``
    are always open. When no token is configured the middleware is a pass-through
    (enabling the guard is intended for shared machines, not localhost).
    """

    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path.startswith("/dashboard/api/") and path not in _AUTH_EXEMPT_PATHS:
            header = request.headers.get("Authorization", "")
            expected = f"Bearer {self._token}"
            if header != expected:
                return JSONResponse(
                    {"detail": "Unauthorized"},
                    status_code=401,
                )
        response: Response = await call_next(request)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # Close the shared proxy httpx clients on shutdown.
    await routes_data.proxy.aclose()
    await routes_queries.proxy.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="BrainPalace Dashboard", version=__version__, lifespan=lifespan)

    token = _resolve_token()
    if token:
        app.add_middleware(BearerTokenMiddleware, token=token)

    @app.get("/dashboard/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(routes_instances.router)
    app.include_router(routes_config.router)
    app.include_router(routes_data.router)
    app.include_router(routes_queries.router)
    app.include_router(routes_events.router)
    app.include_router(routes_settings.router)

    # SPA catch-all is registered last so API routers win.
    _mount_spa(app)

    return app
