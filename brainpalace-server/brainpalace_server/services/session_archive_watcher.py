"""Watch the session archive for deletions and purge the index accordingly.

Mirrors SessionWatcher's watchfiles pattern but reacts to *removals*: when the
user deletes an archived transcript/folder, reconcile the manifest, purge the
session's chunks (delete_by_metadata), and let the service tombstone it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import watchfiles

if TYPE_CHECKING:
    from brainpalace_server.services.session_archive_service import (
        SessionArchiveService,
    )

logger = logging.getLogger(__name__)


class SessionArchiveWatcher:
    """React to archive-file deletions by purging the corresponding chunks."""

    def __init__(
        self,
        archive_dir: str | Path,
        archive: SessionArchiveService,
        storage_backend: Any,
        debounce_ms: int = 1000,
        purge_index: bool = True,
    ) -> None:
        self.archive_dir = Path(archive_dir)
        self.archive = archive
        self.storage_backend = storage_backend
        self.debounce_ms = debounce_ms
        # When indexing is off no chunks exist, so deletions only reconcile the
        # manifest + tombstones — never touch the storage backend.
        self.purge_index = purge_index
        self._stop_event: anyio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    async def purge_deleted(self) -> list[str]:
        """Reconcile deletions and (when indexing) purge removed chunks."""
        removed = self.archive.reconcile_deletions()
        if not self.purge_index or self.storage_backend is None:
            return removed  # archive-only: tombstone + drop manifest, no chunks
        for session_id in removed:
            try:
                # ChromaDB requires $and to combine multiple metadata
                # conditions; a flat multi-key dict is rejected.
                await self.storage_backend.delete_by_metadata(
                    {
                        "$and": [
                            {"source_type": "session_turn"},
                            {"session_id": session_id},
                        ]
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Purge failed for session %s: %s", session_id, exc)
        return removed

    async def start(self) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event = anyio.Event()
        self._task = asyncio.create_task(self._run())

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

    async def _run(self) -> None:
        assert self._stop_event is not None
        try:
            async for _changes in watchfiles.awatch(
                str(self.archive_dir),
                debounce=self.debounce_ms,
                stop_event=self._stop_event,
                recursive=True,
            ):
                await self.purge_deleted()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Archive watcher stopped: %s", exc)
