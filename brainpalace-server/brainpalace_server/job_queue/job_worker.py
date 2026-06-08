"""Background job worker that processes indexing jobs from the queue."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models import IndexingState, IndexingStatusEnum, IndexRequest
from brainpalace_server.models.job import JobProgress, JobRecord, JobStatus
from brainpalace_server.services.indexing_service import IndexingService

if TYPE_CHECKING:
    from brainpalace_server.services.file_watcher_service import FileWatcherService
    from brainpalace_server.services.folder_manager import FolderManager
    from brainpalace_server.services.query_cache import QueryCacheService

logger = logging.getLogger(__name__)


def _should_persist_progress(
    *, last_current: int, current: int, total: int, min_percent: float
) -> bool:
    """Persist when the job completes or progress advanced >= min_percent of
    total. Percent-based so it works for both the pipeline's 0..100 percent
    callbacks and any future file-count caller.
    """
    if current >= total:
        return True
    pct_delta = (current - last_current) / max(total, 1) * 100
    return pct_delta >= min_percent


class CancellationRequestedError(Exception):
    """Raised when a job cancellation is requested."""

    pass


class JobWorker:
    """Background asyncio task that polls for and processes indexing jobs.

    Features:
    - Polls for pending jobs from JobQueueStore
    - Processes one job at a time (concurrency=1)
    - Timeout support with configurable MAX_RUNTIME_SECONDS
    - Cancellation via cancel_requested flag on JobRecord
    - Progress updates at configurable intervals
    - Verifies storage backend has chunks after indexing before marking DONE

    Example:
        worker = JobWorker(job_store, indexing_service)
        await worker.start()
        # ... later ...
        await worker.stop()
    """

    # Default configuration
    MAX_RUNTIME_SECONDS: int = 7200  # 2 hours
    PROGRESS_CHECKPOINT_INTERVAL: int = 50  # Update progress every N files
    PROGRESS_MIN_PERCENT: float = 2.0  # persist every >=2% of total
    POLL_INTERVAL_SECONDS: float = 1.0  # Poll for new jobs every N seconds

    def __init__(
        self,
        job_store: JobQueueStore,
        indexing_service: IndexingService,
        max_runtime_seconds: int | None = None,
        progress_checkpoint_interval: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        """Initialize the job worker.

        Args:
            job_store: Job queue store for persistence.
            indexing_service: Indexing service for processing jobs.
            max_runtime_seconds: Maximum job runtime before timeout.
            progress_checkpoint_interval: Deprecated/ignored — progress
                persistence is now percent-based (see PROGRESS_MIN_PERCENT).
                Still accepted for backward-compatible construction.
            poll_interval_seconds: Poll interval for checking new jobs.
        """
        self._job_store = job_store
        self._indexing_service = indexing_service

        # Configuration (use instance values or defaults)
        self._max_runtime_seconds = max_runtime_seconds or self.MAX_RUNTIME_SECONDS
        self._poll_interval = poll_interval_seconds or self.POLL_INTERVAL_SECONDS
        # Progress persistence is now percent-based via PROGRESS_MIN_PERCENT
        # (see _should_persist_progress). The legacy file-count
        # progress_checkpoint_interval no longer gates persistence; the param is
        # still accepted for backward-compatible construction but is unused.
        self._progress_min_percent = self.PROGRESS_MIN_PERCENT

        # Optional references for watch_mode integration (Phase 15)
        self._file_watcher_service: FileWatcherService | None = None
        self._folder_manager: FolderManager | None = None
        # Optional query cache for invalidation on job completion (Phase 17)
        self._query_cache: QueryCacheService | None = None

        # Internal state
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._current_job: JobRecord | None = None
        self._stop_event = asyncio.Event()

    def set_file_watcher_service(self, service: FileWatcherService | None) -> None:
        """Set the file watcher service for watch_mode integration.

        Called by the lifespan after both JobWorker and FileWatcherService
        are initialized.

        Args:
            service: FileWatcherService instance or None.
        """
        self._file_watcher_service = service

    def set_folder_manager(self, manager: FolderManager | None) -> None:
        """Set the folder manager for watch config updates after job completion.

        Args:
            manager: FolderManager instance or None.
        """
        self._folder_manager = manager

    def set_query_cache(self, cache: QueryCacheService | None) -> None:
        """Set query cache for invalidation on job completion (Phase 17).

        Args:
            cache: QueryCacheService instance or None.
        """
        self._query_cache = cache

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running and self._task is not None and not self._task.done()

    @property
    def current_job(self) -> JobRecord | None:
        """Get the currently processing job, if any."""
        return self._current_job

    async def start(self) -> None:
        """Start the background worker task.

        Creates an asyncio task that polls for pending jobs and processes them.
        Safe to call multiple times (subsequent calls are no-ops if already running).
        """
        if self._running:
            logger.warning("JobWorker already running")
            return

        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("JobWorker started")

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop the worker.

        Signals the worker to stop and waits for the current job to complete
        or for the timeout to expire.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown.
        """
        if not self._running:
            return

        logger.info("JobWorker stopping...")
        self._running = False
        self._stop_event.set()

        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"JobWorker did not stop within {timeout}s, cancelling task"
                )
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        self._task = None
        self._current_job = None
        logger.info("JobWorker stopped")

    async def _run_loop(self) -> None:
        """Main worker loop that polls for and processes jobs.

        Continuously polls for pending jobs and processes them one at a time.
        Exits when stop() is called.
        """
        logger.info("JobWorker run loop started")

        while self._running:
            try:
                # Check for pending jobs
                pending_jobs = await self._job_store.get_pending_jobs()

                if pending_jobs:
                    # Process the first pending job (FIFO)
                    job = pending_jobs[0]
                    await self._process_job(job)
                else:
                    # No jobs, wait before polling again
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self._poll_interval,
                        )
                        # If we get here, stop was requested
                        break
                    except asyncio.TimeoutError:
                        # Normal timeout, continue polling
                        pass

            except Exception as e:
                logger.error(f"Error in job worker loop: {e}", exc_info=True)
                # Brief pause before retrying to avoid tight error loop
                await asyncio.sleep(1.0)

        logger.info("JobWorker run loop exited")

    async def _process_job(self, job: JobRecord) -> None:
        """Process a single indexing job.

        Marks the job as RUNNING, executes the indexing pipeline with timeout,
        and marks the job as DONE, FAILED, or CANCELLED based on outcome.

        Args:
            job: The job record to process.
        """
        logger.info(f"Processing job {job.id} for {job.folder_path}")
        self._current_job = job

        try:
            # Mark job as RUNNING
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            job.progress = JobProgress(
                files_processed=0,
                files_total=0,
                chunks_created=0,
                current_file="",
                updated_at=datetime.now(timezone.utc),
            )
            await self._job_store.update_job(job)

            # Set IndexingService state to indicate indexing is in progress
            # This ensures status endpoints reflect the correct state
            async with self._indexing_service._lock:
                self._indexing_service._state = IndexingState(
                    current_job_id=job.id,
                    status=IndexingStatusEnum.INDEXING,
                    is_indexing=True,
                    folder_path=job.folder_path,
                    started_at=job.started_at,
                    completed_at=None,
                    error=None,
                )

            # Create IndexRequest from JobRecord
            index_request = IndexRequest(
                folder_path=job.folder_path,
                include_code=job.include_code,
                chunk_size=job.chunk_size,
                chunk_overlap=job.chunk_overlap,
                recursive=job.recursive,
                generate_summaries=job.generate_summaries,
                supported_languages=job.supported_languages,
                include_patterns=job.include_patterns,
                include_types=job.include_types,
                exclude_patterns=job.exclude_patterns,
                injector_script=job.injector_script,
                folder_metadata_file=job.folder_metadata_file,
                force=job.force,
            )

            # Build content injector if job has injection params
            content_injector = None
            if job.injector_script or job.folder_metadata_file:
                from brainpalace_server.services.content_injector import ContentInjector

                content_injector = ContentInjector.build(
                    script_path=job.injector_script,
                    metadata_path=job.folder_metadata_file,
                )

            # Create progress callback that checks for cancellation.
            # ``current``/``total`` are the pipeline's phase-weighted PERCENT pair
            # (total is 100), kept separate from the optional real document counts
            # (``files_processed``/``files_total``) so the "Files" display shows
            # actual counts instead of the percent in disguise.
            async def progress_callback(
                current: int,
                total: int,
                message: str,
                files_processed: int | None = None,
                files_total: int | None = None,
            ) -> None:
                """Progress callback that updates job and checks for cancellation."""
                # Re-fetch job to check for cancellation request
                refreshed_job = await self._job_store.get_job(job.id)
                if refreshed_job and refreshed_job.cancel_requested:
                    logger.info(f"Cancellation requested for job {job.id}")
                    raise CancellationRequestedError(
                        f"Job {job.id} cancellation requested"
                    )

                percent = round((current / total) * 100, 1) if total else 0.0
                last_percent = int(job.progress.percent) if job.progress else 0
                # Update progress at intervals
                if job.progress is None or _should_persist_progress(
                    last_current=last_percent,
                    current=current,
                    total=total,
                    min_percent=self._progress_min_percent,
                ):
                    prev = job.progress
                    job.progress = JobProgress(
                        files_processed=(
                            files_processed
                            if files_processed is not None
                            else (prev.files_processed if prev else 0)
                        ),
                        files_total=(
                            files_total
                            if files_total is not None
                            else (prev.files_total if prev else 0)
                        ),
                        chunks_created=prev.chunks_created if prev else 0,
                        current_file=message,
                        percent=percent,
                        updated_at=datetime.now(timezone.utc),
                    )
                    await self._job_store.update_job(job)

            # Get chunk count before indexing for delta verification
            count_before = 0
            try:
                storage = self._indexing_service.storage_backend
                if storage.is_initialized:
                    count_before = await storage.get_count()
            except Exception as e:
                logger.warning(f"Could not get count before indexing: {e}")

            # Execute indexing with timeout
            eviction_result = None
            try:
                eviction_result = await asyncio.wait_for(
                    self._indexing_service._run_indexing_pipeline(
                        index_request,
                        job.id,
                        progress_callback,
                        content_injector=content_injector,
                    ),
                    timeout=self._max_runtime_seconds,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Job {job.id} timed out after {self._max_runtime_seconds}s"
                )
                job.status = JobStatus.FAILED
                job.error = f"Job timed out after {self._max_runtime_seconds} seconds"
                job.finished_at = datetime.now(timezone.utc)
                await self._job_store.update_job(job)

                # Clear IndexingService state on timeout
                async with self._indexing_service._lock:
                    self._indexing_service._state = IndexingState(
                        current_job_id=job.id,
                        status=IndexingStatusEnum.FAILED,
                        is_indexing=False,
                        folder_path=job.folder_path,
                        started_at=job.started_at,
                        completed_at=job.finished_at,
                        error=job.error,
                    )
                return

            # Verify collection has new chunks (delta verification)
            verification_passed = await self._verify_collection_delta(
                job, count_before, eviction_result
            )

            if verification_passed:
                # Get final chunk count from indexing service status
                status = await self._indexing_service.get_status()
                job.total_chunks = status.get("total_chunks", 0)
                job.total_documents = status.get("total_documents", 0)

                # Store eviction summary if present (Phase 14)
                if eviction_result is not None:
                    job.eviction_summary = eviction_result

                # Per-job chunk delta (distinct from the index-wide total_chunks):
                # removed = chunks evicted by this job; added derived from the net
                # store growth plus the eviction, since
                #   count_after = count_before - removed + added.
                chunks_removed = 0
                if isinstance(eviction_result, dict):
                    chunks_removed = int(eviction_result.get("chunks_evicted", 0) or 0)
                count_after = count_before
                try:
                    storage = self._indexing_service.storage_backend
                    if storage.is_initialized:
                        count_after = await storage.get_count()
                except Exception as e:
                    logger.warning(f"Could not get count after indexing: {e}")
                job.chunks_removed = chunks_removed
                job.chunks_added = max(0, count_after - count_before + chunks_removed)

                # Update final progress
                if job.progress:
                    job.progress = JobProgress(
                        files_processed=job.progress.files_total,
                        files_total=job.progress.files_total,
                        chunks_created=job.chunks_added,
                        current_file="Complete",
                        percent=100.0,
                        updated_at=datetime.now(timezone.utc),
                    )

                job.status = JobStatus.DONE
                job.finished_at = datetime.now(timezone.utc)
                logger.info(
                    f"Job {job.id} completed: {job.total_documents} docs, "
                    f"{job.total_chunks} chunks"
                )

                # Clear IndexingService state on success
                async with self._indexing_service._lock:
                    self._indexing_service._state = IndexingState(
                        current_job_id=job.id,
                        status=IndexingStatusEnum.COMPLETED,
                        is_indexing=False,
                        folder_path=job.folder_path,
                        started_at=job.started_at,
                        completed_at=job.finished_at,
                        error=None,
                    )

                # Invalidate query cache on successful reindex (Phase 17 — QCACHE-04)
                if self._query_cache is not None:
                    await self._query_cache.invalidate_all()
                    logger.debug(
                        "Query cache invalidated after job %s completed", job.id
                    )

                # Update watch config and start watcher if watch_mode is set
                await self._apply_watch_config(job)
            else:
                job.status = JobStatus.FAILED
                job.error = "Verification failed: No chunks found in vector store"
                job.finished_at = datetime.now(timezone.utc)
                logger.error(f"Job {job.id} verification failed: no chunks in store")

                # Clear IndexingService state on verification failure
                async with self._indexing_service._lock:
                    self._indexing_service._state = IndexingState(
                        current_job_id=job.id,
                        status=IndexingStatusEnum.FAILED,
                        is_indexing=False,
                        folder_path=job.folder_path,
                        started_at=job.started_at,
                        completed_at=job.finished_at,
                        error=job.error,
                    )

            await self._job_store.update_job(job)

        except CancellationRequestedError:
            job.status = JobStatus.CANCELLED
            job.error = "Job was cancelled by user request"
            job.finished_at = datetime.now(timezone.utc)
            await self._job_store.update_job(job)

            # Clear IndexingService state on cancellation
            async with self._indexing_service._lock:
                self._indexing_service._state = IndexingState(
                    current_job_id=job.id,
                    status=IndexingStatusEnum.IDLE,
                    is_indexing=False,
                    folder_path=job.folder_path,
                    started_at=job.started_at,
                    completed_at=job.finished_at,
                    error=job.error,
                )
            logger.info(f"Job {job.id} cancelled")

        except Exception as e:
            logger.error(f"Job {job.id} failed with error: {e}", exc_info=True)
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.finished_at = datetime.now(timezone.utc)
            await self._job_store.update_job(job)

            # Clear IndexingService state on error
            async with self._indexing_service._lock:
                self._indexing_service._state = IndexingState(
                    current_job_id=job.id,
                    status=IndexingStatusEnum.FAILED,
                    is_indexing=False,
                    folder_path=job.folder_path,
                    started_at=job.started_at,
                    completed_at=job.finished_at,
                    error=job.error,
                )

        finally:
            self._current_job = None

    async def _apply_watch_config(self, job: JobRecord) -> None:
        """Update folder watch config and notify FileWatcherService.

        If the job has watch_mode set, updates the FolderRecord via FolderManager
        and starts/stops file watching accordingly.

        Args:
            job: The completed job record.
        """
        if job.watch_mode is None:
            return

        try:
            # Update FolderRecord with watch config via FolderManager
            if self._folder_manager is not None:
                folder_record = await self._folder_manager.get_folder(job.folder_path)
                if folder_record is not None:
                    # Re-add the folder with updated watch config
                    await self._folder_manager.add_folder(
                        folder_path=folder_record.folder_path,
                        chunk_count=folder_record.chunk_count,
                        chunk_ids=folder_record.chunk_ids,
                        watch_mode=job.watch_mode,
                        watch_debounce_seconds=job.watch_debounce_seconds,
                        include_code=folder_record.include_code,
                    )
                    logger.info(
                        f"Updated watch config for {job.folder_path}: "
                        f"watch_mode={job.watch_mode}"
                    )

            # Notify FileWatcherService
            if self._file_watcher_service is not None:
                if job.watch_mode == "auto":
                    self._file_watcher_service.add_folder_watch(
                        folder_path=job.folder_path,
                        debounce_seconds=job.watch_debounce_seconds,
                    )
                elif job.watch_mode == "off":
                    self._file_watcher_service.remove_folder_watch(job.folder_path)

        except Exception as exc:
            logger.error(
                f"Failed to apply watch config for job {job.id}: {exc!r}",
                exc_info=True,
            )

    async def _verify_collection_delta(
        self,
        job: JobRecord,
        count_before: int,
        eviction_result: dict[str, Any] | None = None,
    ) -> bool:
        """Verify that the vector store has new chunks after indexing.

        Uses delta verification (count_after - count_before) to avoid false
        positives when prior chunks exist but the job added nothing.

        Args:
            job: The job record to verify.
            count_before: Chunk count before indexing started.
            eviction_result: Eviction summary from the indexing pipeline
                (used for zero-change incremental detection).

        Returns:
            True if verification passed (new chunks added), False otherwise.
        """
        try:
            storage = self._indexing_service.storage_backend
            count_after = await storage.get_count()
            delta = count_after - count_before

            if delta > 0:
                logger.info(
                    f"Verification passed for job {job.id}: "
                    f"{delta} new chunks (before={count_before}, after={count_after})"
                )
                return True

            # delta <= 0: net store size did not grow. This is legitimate for an
            # incremental run that only deleted/changed files (eviction), or for
            # a zero-change run where every file was unchanged. Use eviction_result
            # from the pipeline (job.eviction_summary is only set after this
            # verification passes).
            eviction = eviction_result or job.eviction_summary
            if eviction is not None:
                evicted_chunks = eviction.get("chunks_evicted", 0)
                files_deleted = eviction.get("files_deleted", []) or []
                files_changed = eviction.get("files_changed", []) or []
                files_deferred = eviction.get("files_deferred", []) or []
                if (
                    evicted_chunks > 0
                    or files_deleted
                    or files_changed
                    or files_deferred
                ):
                    logger.info(
                        f"Eviction-only/incremental run for job {job.id}: "
                        f"{evicted_chunks} chunks evicted, "
                        f"-{len(files_deleted)} deleted "
                        f"~{len(files_changed)} changed "
                        + (
                            f"!{len(files_deferred)} deferred (re-embed cooldown) "
                            if files_deferred
                            else ""
                        )
                        + f"(before={count_before}, after={count_after})"
                    )
                    return True
                if eviction.get("chunks_to_create", -1) == 0:
                    files_unchanged = eviction.get("files_unchanged", []) or []
                    # Hardening: the manifest claims N files are already indexed
                    # ("unchanged") yet the store is empty. That is a stale-manifest
                    # / store desync — fail loudly instead of silently reporting
                    # done at 0%, so the operator re-indexes with force.
                    if files_unchanged and count_after == 0:
                        logger.error(
                            f"Job {job.id}: manifest reports "
                            f"{len(files_unchanged)} unchanged file(s) but the "
                            "vector store is empty — stale manifest suspected. "
                            "Re-run with force to rebuild."
                        )
                        return False
                    logger.info(
                        f"Zero-change incremental run for job {job.id}: "
                        "all files unchanged, no new chunks expected"
                    )
                    return True

            if delta == 0:
                # Special case: job might have processed files already indexed
                if (
                    count_after > 0
                    and job.progress
                    and (job.progress.files_processed > 0)
                ):
                    logger.warning(
                        f"Job {job.id} processed {job.progress.files_processed} files "
                        f"but added no new chunks (may have been already indexed)"
                    )
                    # Consider this a success if files were processed
                    return True
                logger.warning(
                    f"Verification failed for job {job.id}: no new chunks added "
                    f"(before={count_before}, after={count_after})"
                )
                return False

            logger.warning(
                f"Verification failed for job {job.id}: chunk count decreased "
                f"unexpectedly (before={count_before}, after={count_after})"
            )
            return False

        except Exception as e:
            logger.error(f"Verification error for job {job.id}: {e}")
            return False
