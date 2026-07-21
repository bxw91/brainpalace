"""Phase 050 — live watcher for runtime session transcripts.

A thin, self-contained watcher over a project's external session directory
(``~/.claude/projects/<encoded>/``). On any ``*.jsonl`` change it re-ingests
*that file* via :class:`SessionIndexService` (dedup makes re-ingest cheap).

Deliberately **not** routed through ``FileWatcherService`` — that one is bound
to the folder-manager + job-queue indexing pipeline (code/docs), which would
mis-handle session JSONL. This watcher mirrors its ``watchfiles.awatch`` pattern
but calls the session pipeline directly.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import watchfiles

if TYPE_CHECKING:
    from brainpalace_server.config.session_config import SessionIndexingConfig
    from brainpalace_server.services.session_archive_service import (
        SessionArchiveService,
    )
    from brainpalace_server.services.session_distill_service import SessionDistiller
    from brainpalace_server.services.session_index_service import SessionIndexService

logger = logging.getLogger(__name__)


class SessionWatcher:
    """Watch a session directory and re-ingest changed ``*.jsonl`` files."""

    def __init__(
        self,
        sessions_dir: str | Path,
        service: SessionIndexService | None,
        config: SessionIndexingConfig,
        archive: SessionArchiveService | None = None,
        debounce_ms: int = 2000,
        index_enabled: bool = True,
        distiller: SessionDistiller | None = None,
        adapter: Any | None = None,
        project_root: str | None = None,
    ) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.service = service
        self.config = config
        self.archive = archive
        self.debounce_ms = debounce_ms
        self.index_enabled = index_enabled
        # Phase 080: provider-engine distiller. Present ONLY when the resolved
        # mode is `provider` and SESSION_DISTILL_ENABLED is on — so its presence
        # is the gate. Distills run fire-and-forget; never block the watcher.
        self.distiller = distiller
        # Ownership gate. A tool with a GLOBAL store (codex) surfaces every
        # project's transcripts under one directory; without this filter we
        # would archive another project's raw transcript — user turns and
        # secrets included — into this project's archive.
        self.adapter = adapter
        self.project_root = project_root
        self._stop_event: anyio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    async def _ingest_paths(self, paths: set[str]) -> int:
        """Re-process each changed ``*.jsonl`` path. Returns files handled.

        Archiving (when an archive service is set) always runs. Indexing runs
        only when ``index_enabled`` — so an archive-only project copies the raw
        transcript without ever embedding it.
        """
        count = 0
        for path in sorted(paths):
            if not path.endswith(".jsonl"):
                continue
            if not Path(path).exists():  # deletion / rename-away
                continue
            if (
                self.adapter is not None
                and self.project_root is not None
                and not self.adapter.owns(Path(path), self.project_root)
            ):
                continue  # another project's transcript — never archive it

            archived: Path | None = None
            if self.archive is not None:
                tool = self.adapter.slug if self.adapter is not None else None
                archived = self.archive.sync(path, tool=tool)
                if archived is None:
                    continue  # tombstoned / unreadable: skip entirely
                # Phase 080: schedule a provider-engine distill of the archived
                # transcript (gated quiescent + un-marked inside the distiller).
                # Fire-and-forget — never blocks archiving/indexing.
                if self.distiller is not None:
                    self.distiller.schedule(archived)

            if not self.index_enabled or self.service is None:
                # Archive-only: copied above (if archive set), never indexed.
                if archived is not None:
                    count += 1
                continue

            if archived is not None:
                target: str | Path = archived
                origin_path: str | None = str(path)
            else:
                target = path  # legacy: no archive, index the live file directly
                origin_path = None
            try:
                await self.service.index_session_file(
                    target,
                    include_user_turns=self.config.include_user_turns,
                    window=self.config.window,
                    stride=self.config.stride,
                    origin_path=origin_path,
                )
                count += 1
            except (
                Exception
            ) as exc:  # noqa: BLE001 — one bad file must not kill the watcher
                logger.warning("session watcher: ingest failed for %s: %s", target, exc)
        return count

    async def _loop(self) -> None:
        assert self._stop_event is not None
        logger.info("Session watcher started for %s", self.sessions_dir)
        try:
            async for changes in watchfiles.awatch(
                str(self.sessions_dir),
                debounce=self.debounce_ms,
                stop_event=self._stop_event,
                recursive=True,
            ):
                await self._ingest_paths({path for _change, path in changes})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Session watcher error for %s: %r", self.sessions_dir, exc)

    async def start(self) -> None:
        """Launch the watch loop. No-op if the directory does not exist."""
        if not self.sessions_dir.exists():
            logger.info(
                "Session watcher: %s does not exist — not watching.",
                self.sessions_dir,
            )
            return
        self._stop_event = anyio.Event()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
