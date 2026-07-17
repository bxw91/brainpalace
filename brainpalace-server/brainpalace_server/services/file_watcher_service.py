"""File watcher service for automatic incremental re-indexing.

This module provides FileWatcherService, which starts one asyncio task per
auto-mode folder using watchfiles.awatch(). When file changes are detected,
it enqueues an incremental indexing job via the job queue (deduplicated, force=False).

Key design decisions:
- One asyncio Task per folder (independent lifecycle)
- anyio.Event for clean shutdown (watchfiles supports stop_event natively)
- Deduplication via existing dedupe_key mechanism (no double-indexing)
- source="watch" marks watcher-triggered jobs (provenance flows to FolderRecord.source)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import watchfiles
from watchfiles import Change, DefaultFilter

from brainpalace_server.config.runtime_mode import is_read_only
from brainpalace_server.models.index import IndexRequest

if TYPE_CHECKING:
    from brainpalace_server.indexing.gitignore_matcher import GitignoreMatcher
    from brainpalace_server.job_queue.job_service import JobQueueService
    from brainpalace_server.services.folder_manager import FolderManager

logger = logging.getLogger(__name__)


# Directories to exclude from watching (extends DefaultFilter defaults).
# `.brainpalace` is the server's own state dir (chroma_db, embedding_cache,
# jobs, logs). Without excluding it, every server write would re-trigger the
# watcher and enqueue another reindex job — the root cause of issue #123.
_EXTRA_IGNORE_DIRS = frozenset(
    {
        ".brainpalace",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        "htmlcov",
    }
)


class BrainPalaceWatchFilter(DefaultFilter):
    """Custom watchfiles filter: extends DefaultFilter with extra ignore dirs.

    DefaultFilter already ignores .git/, __pycache__/, node_modules/, .tox,
    .venv, etc. This subclass adds project-specific build-artifact directories
    AND (when a GitignoreMatcher is supplied) honours the project's
    `.gitignore` files. See Phase H.
    """

    ignore_dirs: tuple[str, ...] = tuple(DefaultFilter.ignore_dirs) + tuple(
        _EXTRA_IGNORE_DIRS
    )

    def __init__(
        self,
        gitignore_matcher: GitignoreMatcher | None = None,
        watch_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._gitignore_matcher = gitignore_matcher
        self._watch_root = watch_root

    def _under_nested_project(self, path: Path) -> bool:
        """True when ``path`` lives inside a subfolder that has its own
        ``.brainpalace/`` (a separately-indexed nested project).

        Climbs from the path's parent up to — but not including — the watch
        root, so the outer project's own `.brainpalace/` never counts. Checked
        live, so deleting the nested `.brainpalace/` re-enables watching.
        """
        if self._watch_root is None:
            return False
        cur = path.parent
        try:
            while cur != self._watch_root:
                if (cur / ".brainpalace").is_dir():
                    return True
                if cur.parent == cur:  # filesystem root — safety stop
                    return False
                cur = cur.parent
        except OSError:
            return False
        return False

    def __call__(self, change: Change, path: str) -> bool:
        if not super().__call__(change, path):
            return False
        if self._gitignore_matcher is not None:
            if self._gitignore_matcher.is_ignored(Path(path)):
                return False
        if self._under_nested_project(Path(path)):
            return False
        return True


async def _watch_folder_loop(
    folder_path: str,
    debounce_ms: int,
    stop_event: anyio.Event,
    enqueue_callback: Callable[[str], Awaitable[None]],
    watch_filter: BrainPalaceWatchFilter,
) -> None:
    """Async loop that watches a folder and enqueues jobs on changes.

    Args:
        folder_path: Absolute path to the folder to watch.
        debounce_ms: Debounce interval in milliseconds.
        stop_event: anyio.Event — when set, the watcher exits cleanly.
        enqueue_callback: Async callable invoked with folder_path on each change.
        watch_filter: Pre-built BrainPalaceWatchFilter (may include gitignore matcher).
    """
    logger.info(
        f"File watcher started for {folder_path} " f"(debounce={debounce_ms}ms)"
    )
    try:
        async for _changes in watchfiles.awatch(
            folder_path,
            debounce=debounce_ms,
            stop_event=stop_event,
            recursive=True,
            watch_filter=watch_filter,
        ):
            logger.debug(
                f"File changes detected in {folder_path} " f"({len(_changes)} event(s))"
            )
            await enqueue_callback(folder_path)
    except asyncio.CancelledError:
        logger.info(f"File watcher task cancelled for {folder_path}")
        raise
    except Exception as exc:
        logger.error(
            f"File watcher error for {folder_path}: {exc!r} — stopping watcher",
            exc_info=True,
        )


class FileWatcherService:
    """Manages per-folder asyncio tasks for file watching.

    On server startup, starts one asyncio Task per folder with watch_mode='auto'.
    On file change, enqueues an incremental indexing job (deduplicated, force=False).
    On shutdown, cleans up all watcher tasks gracefully via anyio.Event.

    Usage::

        service = FileWatcherService(folder_manager, job_service, debounce_seconds=30)
        await service.start()
        # ... server running ...
        await service.stop()
    """

    def __init__(
        self,
        folder_manager: FolderManager,
        job_service: JobQueueService,
        default_debounce_seconds: int = 30,
        post_enqueue_cooldown_seconds: int = 10,
        gitignore_matcher: GitignoreMatcher | None = None,
    ) -> None:
        """Initialize FileWatcherService.

        Args:
            folder_manager: FolderManager instance for listing/getting folder records.
            job_service: JobQueueService instance for enqueueing jobs.
            default_debounce_seconds: Global debounce in seconds for folders without
                a per-folder override.
            post_enqueue_cooldown_seconds: Minimum gap, per folder, between two
                watcher-triggered enqueues. Suppresses delayed-inotify replays
                that arrive after a previous job already transitioned to DONE
                (so dedupe_key no longer matches). Set to 0 to disable.
            gitignore_matcher: Optional project-local `.gitignore` matcher
                (Phase H). When provided, the watcher filter consults it so
                events for ignored paths never propagate.
        """
        self._folder_manager = folder_manager
        self._job_service = job_service
        self._default_debounce_seconds = default_debounce_seconds
        self._post_enqueue_cooldown_seconds = post_enqueue_cooldown_seconds
        self._gitignore_matcher = gitignore_matcher
        self._stop_event: anyio.Event | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_enqueue_at: dict[str, float] = {}
        # Wall-clock (unlike _last_enqueue_at, which is monotonic and not
        # comparable to a persisted JobRecord's wall-clock blocked_since).
        # Used by the blocked-job reaper (Fix 2, D6) to detect "did the
        # watcher see a change for this folder after it blocked".
        self._last_change_at: dict[str, datetime] = {}

        # Task 4d: optional pending store for backpressure; injected via
        # set_doc_pending_store after startup.
        self._doc_pending_store: object | None = None
        self._watcher_paused: bool = False  # hysteresis state

    def set_doc_pending_store(self, store: object | None) -> None:
        """Inject the DocPendingStore for backpressure (Task 4d).

        When set, ``_enqueue_for_folder`` skips enqueuing new watch-triggered
        jobs while the extraction queue is at the high-water mark.
        """
        self._doc_pending_store = store

    @property
    def watched_folder_count(self) -> int:
        """Number of folders currently being watched."""
        return len(self._tasks)

    def last_change_at(self, folder_path: str) -> datetime | None:
        """Wall-clock time of the most recent watcher-observed change for
        ``folder_path``, or None if the watcher has never seen a change for
        it (e.g. an unwatched folder, or watched but quiet since startup).

        Used by the blocked-job reaper (Fix 2, D6): a blocked job's folder is
        revalidated only when this timestamp is newer than the job's
        ``blocked_since``.
        """
        return self._last_change_at.get(folder_path)

    def dead_task_count(self) -> int:
        """Number of watch tasks that have exited/raised (should be 0 when healthy)."""
        return sum(1 for t in self._tasks.values() if t.done())

    async def expected_auto_folder_count(self) -> int:
        """How many folders SHOULD be watched (watch_mode == 'auto')."""
        folders = await self._folder_manager.list_folders()
        return sum(1 for f in folders if f.watch_mode == "auto")

    @property
    def is_running(self) -> bool:
        """True if the watcher service has been started and not yet stopped."""
        return self._stop_event is not None and not self._stop_event.is_set()

    async def start(self) -> None:
        """Start the file watcher service.

        Creates an anyio.Event (must be called inside an async context) and
        launches a watcher task for each folder with watch_mode='auto'.
        """
        # anyio.Event MUST be created inside an async context
        self._stop_event = anyio.Event()

        folders = await self._folder_manager.list_folders()
        auto_folders = [f for f in folders if f.watch_mode == "auto"]

        for folder_record in auto_folders:
            self._start_task(
                folder_path=folder_record.folder_path,
                debounce_seconds=folder_record.watch_debounce_seconds,
            )

        logger.info(
            f"FileWatcherService started: watching {len(auto_folders)} "
            f"folder(s) (default debounce={self._default_debounce_seconds}s)"
        )

    async def stop(self) -> None:
        """Stop the file watcher service gracefully.

        Sets the stop_event (signals watchfiles.awatch to exit), cancels all
        tasks, and waits for them to finish.
        """
        if self._stop_event is not None:
            self._stop_event.set()

        # Cancel and await all watcher tasks
        tasks_snapshot = list(self._tasks.items())
        for _folder_path, task in tasks_snapshot:
            if not task.done():
                task.cancel()

        for _folder_path, task in tasks_snapshot:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        self._tasks.clear()
        logger.info("FileWatcherService stopped")

    def add_folder_watch(
        self,
        folder_path: str,
        debounce_seconds: int | None = None,
    ) -> None:
        """Start watching a new folder.

        Called after a folder is registered with watch_mode='auto'.
        No-op if the service is not running or already watching the folder.

        Args:
            folder_path: Absolute path to the folder to watch.
            debounce_seconds: Per-folder debounce (None = use global default).
        """
        if not self.is_running:
            logger.debug(
                f"add_folder_watch called but service not running " f"for {folder_path}"
            )
            return

        if folder_path in self._tasks:
            logger.debug(f"Already watching {folder_path}")
            return

        self._start_task(folder_path=folder_path, debounce_seconds=debounce_seconds)
        logger.info(f"Added file watcher for {folder_path}")

    def remove_folder_watch(self, folder_path: str) -> None:
        """Stop watching a folder.

        Called when a folder is removed or its watch_mode is set to 'off'.

        Args:
            folder_path: Absolute path to the folder to stop watching.
        """
        task = self._tasks.pop(folder_path, None)
        if task is not None and not task.done():
            task.cancel()
            logger.info(f"Removed file watcher for {folder_path}")
        else:
            logger.debug(f"No active watcher to remove for {folder_path}")

    def _start_task(
        self,
        folder_path: str,
        debounce_seconds: int | None,
    ) -> None:
        """Create and register an asyncio task for watching a folder.

        Args:
            folder_path: Absolute path to the folder.
            debounce_seconds: Per-folder override (None = use global default).
        """
        effective_debounce = debounce_seconds or self._default_debounce_seconds
        debounce_ms = effective_debounce * 1000

        assert (
            self._stop_event is not None
        ), "_start_task called before start() — stop_event is None"

        task = asyncio.create_task(
            _watch_folder_loop(
                folder_path=folder_path,
                debounce_ms=debounce_ms,
                stop_event=self._stop_event,
                enqueue_callback=self._enqueue_for_folder,
                watch_filter=BrainPalaceWatchFilter(
                    gitignore_matcher=self._gitignore_matcher,
                    watch_root=Path(folder_path),
                ),
            ),
            name=f"watcher:{folder_path}",
        )
        self._tasks[folder_path] = task

    async def _enqueue_for_folder(self, folder_path: str) -> None:
        """Enqueue an incremental indexing job for the given folder.

        Reads include_code from the folder's FolderRecord and creates an
        IndexRequest with force=False (rely on ManifestTracker for incremental).
        Deduplication by existing dedupe_key mechanism prevents double-indexing.

        Args:
            folder_path: Absolute path to the changed folder.
        """
        if is_read_only():
            logger.debug(
                "read-only: skipping watcher reindex enqueue for %s", folder_path
            )
            return
        # Task 4d: skip enqueueing when the extraction queue is at the
        # high-water mark.  The watcher will fire again on the next file
        # event, so coverage is delayed — never dropped.
        if self._doc_pending_store is not None:
            try:
                from brainpalace_server.config.extraction_config import (
                    load_extraction_config,
                )
                from brainpalace_server.services.backpressure import (
                    should_pause_indexing,
                )

                _ext_cfg = load_extraction_config()
                _max_pending = _ext_cfg.max_pending
                if _max_pending > 0:
                    _count = int(
                        getattr(self._doc_pending_store, "count_pending", lambda: 0)()
                    )
                    _pause = should_pause_indexing(
                        _count, _max_pending, resumed=self._watcher_paused
                    )
                    if _pause:
                        if not self._watcher_paused:
                            logger.warning(
                                "File-watcher enqueue paused: extraction queue at %d "
                                "items (>= max_pending=%d). Will resume below %d.",
                                _count,
                                _max_pending,
                                int(_max_pending * 0.8),
                            )
                            self._watcher_paused = True
                        return
                    elif self._watcher_paused:
                        logger.info(
                            "File-watcher enqueue resumed: extraction queue at %d "
                            "items (< low-water %d).",
                            _count,
                            int(_max_pending * 0.8),
                        )
                        self._watcher_paused = False
            except Exception:  # noqa: BLE001 — never block the watcher
                pass
        try:
            # Post-enqueue cooldown: collapse delayed-inotify replays that
            # arrive after a prior job already transitioned to DONE.
            if self._post_enqueue_cooldown_seconds > 0:
                now = time.monotonic()
                last = self._last_enqueue_at.get(folder_path, 0.0)
                elapsed = now - last
                if last > 0.0 and elapsed < self._post_enqueue_cooldown_seconds:
                    logger.debug(
                        f"File watcher cooldown skip for {folder_path} "
                        f"({elapsed:.1f}s < "
                        f"{self._post_enqueue_cooldown_seconds}s)"
                    )
                    return

            folder_record = await self._folder_manager.get_folder(folder_path)
            if folder_record is None:
                logger.warning(
                    f"File watcher: folder record not found for {folder_path} "
                    f"— skipping enqueue"
                )
                return

            include_code = folder_record.include_code
            request = IndexRequest(
                folder_path=folder_path,
                include_code=include_code,
                recursive=True,
                force=False,
                trigger="watch",
            )
            response = await self._job_service.enqueue_job(
                request=request,
                operation="index",
                force=False,
                allow_external=True,
                source="watch",
            )

            # Stamp regardless of dedupe_hit — both signal that a job for
            # this folder is currently in flight, so further events should
            # honour the cooldown window.
            self._last_enqueue_at[folder_path] = time.monotonic()
            # Wall-clock counterpart for the blocked-job reaper (Fix 2): a
            # dedupe_hit here still means the watcher observed a real change
            # for this folder — exactly the signal the reaper needs to
            # decide a blocked job's folder is worth revalidating.
            self._last_change_at[folder_path] = datetime.now(timezone.utc)

            if response.dedupe_hit:
                logger.debug(
                    f"File watcher dedupe hit for {folder_path} "
                    f"(existing job: {response.job_id})"
                )
            else:
                logger.info(
                    f"File watcher enqueued job {response.job_id} " f"for {folder_path}"
                )

        except Exception as exc:
            logger.error(
                f"File watcher failed to enqueue job for {folder_path}: {exc!r}",
                exc_info=True,
            )
