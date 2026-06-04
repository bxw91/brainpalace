"""Periodic session-archive reconcile: copy (sync) + optional index + distiller
catch-up on a timer, replacing the per-event copy watcher. Copy cadence is the
``reconcile_seconds`` interval; ``sync`` dedups unchanged files so a quiet session
is copied once (final flush) and never re-summarized."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from brainpalace_server.config.session_config import retain_cutoff
from brainpalace_server.services.session_index_service import discover_session_files

logger = logging.getLogger(__name__)


async def reconcile_once(
    *,
    sessions_dir: Path,
    archive_service: Any | None,
    sess_svc: Any | None,
    session_cfg: Any,
    caps: Any,
    distiller: Any | None,
) -> dict[str, int]:
    """One sweep: sync each live transcript, index when enabled, catch-up distil.

    Returns ``{"archived": int, "indexed": int}``. ``sync`` is idempotent on
    unchanged files, so repeated sweeps copy a session at most once per real
    change (the final tail is captured on the first sweep after it goes quiet).
    """
    live_files = discover_session_files(sessions_dir)
    cutoff = retain_cutoff(session_cfg.retain_days)
    archived = indexed = 0
    arch_paths: list[Path] = []
    for live in live_files:
        arch = None
        if archive_service is not None:
            arch = archive_service.sync(live)
            if arch is None:
                continue  # tombstoned / unreadable
            archived += 1
            arch_paths.append(arch)
        if not caps.index_enabled or sess_svc is None:
            continue
        if cutoff is not None:
            try:
                if live.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
        await sess_svc.index_session_file(
            arch if arch is not None else live,
            include_user_turns=session_cfg.include_user_turns,
            window=session_cfg.window,
            stride=session_cfg.stride,
            origin_path=str(live) if arch is not None else None,
        )
        indexed += 1
    if distiller is not None and arch_paths:
        with contextlib.suppress(Exception):
            await distiller.catch_up(arch_paths)
    return {"archived": archived, "indexed": indexed}


class SessionReconciler:
    """Runs ``reconcile_once`` immediately, then every ``interval_seconds``."""

    def __init__(
        self,
        *,
        interval_seconds: int,
        sessions_dir: Path,
        archive_service: Any | None,
        sess_svc: Any | None,
        session_cfg: Any,
        caps: Any,
        distiller: Any | None,
    ) -> None:
        self.interval_seconds = max(1, interval_seconds)
        self._kw: dict[str, Any] = {
            "sessions_dir": sessions_dir,
            "archive_service": archive_service,
            "sess_svc": sess_svc,
            "session_cfg": session_cfg,
            "caps": caps,
            "distiller": distiller,
        }
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _tick(self) -> dict[str, int]:
        try:
            return await reconcile_once(**self._kw)
        except Exception as exc:  # noqa: BLE001 — one bad sweep must not kill the loop
            logger.warning("session reconcile sweep failed: %s", exc)
            return {"archived": 0, "indexed": 0}

    async def _loop(self) -> None:
        await self._tick()  # immediate first sweep
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                await self._tick()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
