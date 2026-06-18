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

# Run the destructive manifest-orphan deep-clean far less often than the cheap
# heals — every Nth heartbeat (~30 min at HEARTBEAT_SECONDS=180), and only when
# nothing is indexing.
DEEP_CLEAN_EVERY_TICKS = 10

# Consecutive heartbeats a *live* dashboard must fail its health probe before we
# tear it down and relaunch. The probe is a tight 2s GET (dashboard_status); a
# single miss under load is a false negative, and relaunching on it caused a
# kill/relaunch flap that drifted the dashboard off its configured port
# (8787 → 8788 → …). A genuinely dead dashboard reports `not_running` (pid gone)
# and is relaunched immediately — only the alive-but-unhealthy case is debounced.
DASHBOARD_UNHEALTHY_STRIKES = 3


class HealState:
    """Carries cross-tick counters (worker restart budget + deep-clean cadence)."""

    def __init__(self) -> None:
        self.worker_restarts = 0
        self.tick = 0
        # Consecutive heartbeats the dashboard was alive-but-unhealthy. Reset on
        # any healthy probe or after a relaunch; gates the flap-prone teardown.
        self.dashboard_unhealthy_strikes = 0


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
    # Heal both the code index and the memory shadow index; each is a cheap
    # no-op when healthy, so running it every heartbeat catches a corruption
    # that develops mid-session before it can crash the next upsert.
    for attr, label in (("vector_store", "code"), ("mem_vector_store", "memory")):
        vector = getattr(app.state, attr, None)
        if vector is None:
            continue
        try:
            rebuilt = await vector.heal_if_corrupt()
            if rebuilt:
                logger.warning(
                    "%s vector index heal rebuilt %d vectors", label, rebuilt
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s index heal failed: %s", label, exc)


def _heal_dashboard(healer: HealState | None = None) -> None:
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
            # The dashboard is spawned in-process (Popen) by this server, so a
            # dashboard that exited but wasn't wait()ed for lingers as a zombie
            # — and a zombie answers os.kill(pid,0) as alive, poisoning the
            # singleton pidfile so ensure_running would never relaunch. Reap our
            # tracked dashboard child first if it has exited.
            rt = dash.read_dashboard_runtime()
            if rt:
                child_pid = int(rt.get("pid", -1))
                if child_pid > 0:
                    try:
                        os.waitpid(child_pid, os.WNOHANG)
                    except (ChildProcessError, OSError):
                        pass  # not our child / already reaped — fine

            # Debounce the relaunch decision instead of calling ensure_running
            # blindly: a live dashboard that merely *missed* its 2s health probe
            # under load must NOT be torn down, or it flaps (kill → relaunch →
            # port climb 8787→8788→…). Only relaunch when the dashboard is truly
            # down (pid gone) OR it has been alive-but-unhealthy for
            # DASHBOARD_UNHEALTHY_STRIKES consecutive heartbeats.
            status = dash.dashboard_status()
            running = status.get("status") == "running"
            healthy = bool(status.get("healthy"))
            if running and healthy:
                if healer is not None:
                    healer.dashboard_unhealthy_strikes = 0
                return
            if running and not healthy and healer is not None:
                healer.dashboard_unhealthy_strikes += 1
                if healer.dashboard_unhealthy_strikes < DASHBOARD_UNHEALTHY_STRIKES:
                    logger.debug(
                        "dashboard alive but unhealthy (strike %d/%d) — deferring "
                        "relaunch to avoid a transient-probe flap",
                        healer.dashboard_unhealthy_strikes,
                        DASHBOARD_UNHEALTHY_STRIKES,
                    )
                    return
            # Confirmed down, or unhealthy past the strike budget: relaunch and
            # reset the counter. ensure_running clears a poisoned pidfile itself.
            if healer is not None:
                healer.dashboard_unhealthy_strikes = 0
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


async def _indexing_in_progress(app: FastAPI) -> bool:
    """True if any index work is running — the deep-clean must skip then.

    A mid-index store is transiently inconsistent (chunks added before the
    manifest is saved), so running the manifest-orphan delete during indexing
    could reap just-written chunks.
    """
    svc = getattr(app.state, "indexing_service", None)
    if svc is not None and getattr(getattr(svc, "_state", None), "is_indexing", False):
        return True
    job_service = getattr(app.state, "job_service", None)
    if job_service is not None:
        try:
            stats = await job_service.get_queue_stats()
            if stats.running or stats.pending:
                return True
        except Exception:  # noqa: BLE001 — unknown → assume busy (safer)
            return True
    return False


async def _deep_clean(app: FastAPI, healer: HealState) -> None:
    """Periodic manifest-orphan cleanup — gated on cadence + idle. Never raises."""
    healer.tick += 1
    if healer.tick % DEEP_CLEAN_EVERY_TICKS != 0:
        return
    folder_manager = getattr(app.state, "folder_manager", None)
    manifest_tracker = getattr(app.state, "manifest_tracker", None)
    storage_backend = getattr(app.state, "storage_backend", None)
    if folder_manager is None or manifest_tracker is None or storage_backend is None:
        return
    if await _indexing_in_progress(app):
        logger.debug("deep-clean skipped: indexing in progress")
        return
    try:
        from brainpalace_server.services.startup_reconcile import deep_clean

        archive_service = getattr(app.state, "session_archive_service", None)
        archive_dir = getattr(archive_service, "archive_dir", None)
        repo_path = getattr(app.state, "project_root", "") or None

        summary = await deep_clean(
            folder_manager,
            manifest_tracker,
            storage_backend,
            archive_dir=archive_dir,
            repo_path=repo_path,
        )
        if (
            summary.folders_removed
            or summary.orphan_chunks_removed
            or summary.session_chunks_removed
            or summary.git_chunks_removed
        ):
            logger.warning(
                "Periodic deep-clean: removed %d missing folder(s), %d orphan "
                "code/doc chunk(s), %d session chunk(s), %d git chunk(s)",
                summary.folders_removed,
                summary.orphan_chunks_removed,
                summary.session_chunks_removed,
                summary.git_chunks_removed,
            )
    except Exception as exc:  # noqa: BLE001 — never let the heartbeat die
        logger.warning("deep-clean failed: %s", exc)


async def heal_once(app: FastAPI, healer: HealState) -> None:
    """One heartbeat tick: re-assert registration + run all heals. Never raises."""
    await _reassert_registration(app)
    await _heal_watcher(app)
    await _heal_worker(app, healer)
    await _heal_index(app)
    await _deep_clean(app, healer)
    await asyncio.to_thread(_heal_dashboard, healer)


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
