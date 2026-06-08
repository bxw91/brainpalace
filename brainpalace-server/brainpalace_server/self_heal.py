"""The running server keeps its own registration + dependents healthy.

Two entry points used by ``api/main.py``:
- ``registration_middleware(app)`` — learns the real bind address from the first
  request and registers off the response path.
- ``heartbeat_loop(app)`` — every ``HEARTBEAT_SECONDS`` re-asserts registration
  and heals the dashboard, file watcher, job worker, and vector index.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from brainpalace_server import registry
from brainpalace_server.runtime import RuntimeState, write_runtime

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 180


def address_from_scope(
    scope: Mapping[str, Any], headers_host: str | None
) -> tuple[str, int, str]:
    """Derive (bind_host, port, base_url) from the ASGI scope's bound socket.

    Deliberately ignores the (spoofable) Host header — the bound socket in
    ``scope['server']`` is authoritative. ``0.0.0.0``/None host -> ``127.0.0.1``.
    """
    server = scope.get("server") or ("127.0.0.1", 0)
    host, port = server[0], int(server[1] or 0)
    if host in (None, "", "0.0.0.0", "::"):
        host = "127.0.0.1"
    scheme = scope.get("scheme", "http")
    return host, port, f"{scheme}://{host}:{port}"


def register(
    state_dir: Path,
    project_root: Path,
    *,
    base_url: str,
    bind_host: str,
    port: int,
) -> None:
    """Write runtime.json + upsert the registry entry. Best-effort."""
    try:
        rs = RuntimeState(
            mode="project",
            project_root=str(project_root),
            bind_host=bind_host,
            port=port,
            pid=os.getpid(),
            base_url=base_url,
        )
        write_runtime(state_dir, rs)
        registry.upsert_entry(project_root, state_dir)
    except Exception as exc:  # noqa: BLE001 — never propagate
        logger.warning("self-registration failed: %s", exc)


def registration_middleware(
    app: FastAPI,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Return an ASGI http middleware that registers off the response path.

    Learns the bound address from the request scope on the first hit (or when it
    changes), caches it on ``app.state.registered_base_url``, and schedules the
    file writes via ``asyncio.create_task`` so the response is never blocked.
    """

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            st = app.state
            state_dir = getattr(st, "state_dir", None)
            project_root = getattr(st, "project_root", "") or ""
            if state_dir and project_root:
                host, port, base_url = address_from_scope(
                    request.scope, request.headers.get("host")
                )
                if port and base_url != getattr(st, "registered_base_url", None):
                    st.registered_base_url = base_url
                    asyncio.create_task(
                        asyncio.to_thread(
                            register,
                            Path(state_dir),
                            Path(project_root),
                            base_url=base_url,
                            bind_host=host,
                            port=port,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — never affect the response
            logger.debug("registration middleware skipped: %s", exc)
        return await call_next(request)

    return middleware


MAX_WORKER_RESTARTS = 5


class HealState:
    """Carries cross-tick counters (worker restart budget)."""

    def __init__(self) -> None:
        self.worker_restarts = 0


async def _heal_watcher(app: FastAPI) -> None:
    watcher = getattr(app.state, "file_watcher_service", None)
    if watcher is None:
        return
    try:
        expected = await watcher.expected_auto_folder_count()
        if expected == 0:
            return
        unhealthy = (
            watcher.dead_task_count() > 0 or watcher.watched_folder_count < expected
        )
        if unhealthy:
            logger.warning("file watcher unhealthy — restarting")
            await watcher.stop()
            await watcher.start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher heal failed: %s", exc)


async def _heal_worker(app: FastAPI, healer: HealState) -> None:
    worker = getattr(app.state, "job_worker", None)
    if worker is None or worker.is_running():
        return
    if healer.worker_restarts >= MAX_WORKER_RESTARTS:
        return  # give up; /health reflects unhealthy
    try:
        healer.worker_restarts += 1
        logger.warning(
            "job worker not running — restart %d/%d",
            healer.worker_restarts,
            MAX_WORKER_RESTARTS,
        )
        await worker.start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("worker heal failed: %s", exc)


async def _heal_index(app: FastAPI) -> None:
    vector = getattr(app.state, "vector_store", None)
    if vector is None:
        return
    try:
        rebuilt = await vector.heal_if_corrupt()
        if rebuilt:
            logger.warning("vector index heal rebuilt %d vectors", rebuilt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("index heal failed: %s", exc)


def _heal_dashboard() -> None:
    try:
        from brainpalace_dashboard import server as dash  # optional, guarded
        from brainpalace_dashboard.config import load_dashboard_config
    except ImportError:
        return  # dashboard not installed (e.g. Python < 3.12)
    try:
        if not load_dashboard_config().autostart:
            return
        from brainpalace_server.locking import file_lock
        from brainpalace_server.registry import get_xdg_state_dir

        lock_path = get_xdg_state_dir() / "dashboard.launch.lock"
        with file_lock(lock_path):  # serialize launches across project servers
            dash.ensure_running(open_browser_if_new=False)
    except Exception as exc:  # noqa: BLE001 — never affect the server
        logger.debug("dashboard heal skipped: %s", exc)


async def _reassert_registration(app: FastAPI) -> None:
    base_url = getattr(app.state, "registered_base_url", None)
    state_dir = getattr(app.state, "state_dir", None)
    project_root = getattr(app.state, "project_root", "") or ""
    if not (base_url and state_dir and project_root):
        return  # no request seen yet — nothing to re-assert
    host = base_url.split("://", 1)[-1].rsplit(":", 1)[0]
    port = int(base_url.rsplit(":", 1)[-1])
    await asyncio.to_thread(
        register,
        Path(state_dir),
        Path(project_root),
        base_url=base_url,
        bind_host=host,
        port=port,
    )


async def heal_once(app: FastAPI, healer: HealState) -> None:
    """One heartbeat tick: re-assert registration + run all heals. Never raises."""
    await _reassert_registration(app)
    await _heal_watcher(app)
    await _heal_worker(app, healer)
    await _heal_index(app)
    await asyncio.to_thread(_heal_dashboard)


async def heartbeat_loop(app: FastAPI) -> None:
    """Run ``heal_once`` every ``HEARTBEAT_SECONDS`` until cancelled."""
    healer = HealState()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                await heal_once(app, healer)
            except Exception as exc:  # noqa: BLE001 — loop must survive
                logger.warning("heartbeat tick failed: %s", exc)
    except asyncio.CancelledError:
        pass
