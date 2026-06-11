"""Tests for git-history job queue integration (Issue #15).

Covers:
1. JobRecord.job_type defaults to "documents"; old serialized row without
   job_type still loads.
2. JobWorker dispatches job_type=="git_history" to _process_git_job.
   - DONE on 0-delta (incremental reindex with no new commits)
   - FAILED when index_repo raises
   - chunks_added == max(0, after - before)
3. Dedupe: two consecutive enqueue_git_history_job while first PENDING →
   second returns dedupe_hit=True with same job_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.job_queue.job_worker import JobWorker
from brainpalace_server.models.job import JobRecord, JobStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_job(folder: str = "/repo/myproject") -> JobRecord:
    """Create a minimal git_history JobRecord."""
    return JobRecord(
        id="job_git001",
        job_type="git_history",
        dedupe_key=JobRecord.compute_git_dedupe_key(folder),
        folder_path=folder,
        source="git",
        operation="index",
        status=JobStatus.PENDING,
    )


def _make_worker_for_git(
    count_before: int = 0,
    count_after: int = 0,
) -> tuple[JobWorker, AsyncMock, AsyncMock]:
    """Build a JobWorker with mocked indexing_service + job_store.

    Returns (worker, mock_job_store, mock_git_index_service).
    """
    mock_storage = MagicMock()
    mock_storage.is_initialized = True
    # get_count called twice: once before, once after
    mock_storage.get_count = AsyncMock(side_effect=[count_before, count_after])

    mock_indexing_service = MagicMock()
    mock_indexing_service.storage_backend = mock_storage
    mock_indexing_service.get_status = AsyncMock(
        return_value={"total_chunks": count_after, "total_documents": 1}
    )
    # _lock used by doc-path but NOT by git path; provide a real asyncio lock
    # so the attribute exists (git path doesn't touch it, but worker init does)
    import asyncio

    mock_indexing_service._lock = asyncio.Lock()

    mock_job_store = AsyncMock()
    mock_job_store.update_job = AsyncMock()

    mock_git_svc = AsyncMock()
    mock_git_svc.index_repo = AsyncMock(return_value={"commits_new": 0, "skipped": 0})

    worker = JobWorker(
        job_store=mock_job_store,
        indexing_service=mock_indexing_service,
    )
    return worker, mock_job_store, mock_git_svc


# ===========================================================================
# 1. JobRecord.job_type field
# ===========================================================================


class TestJobRecordJobType:
    """JobRecord.job_type defaults and back-compat."""

    def test_job_type_defaults_to_documents(self) -> None:
        """A freshly created JobRecord without job_type gets 'documents'."""
        job = JobRecord(
            id="job_x",
            dedupe_key=JobRecord.compute_dedupe_key(
                folder_path="/p",
                include_code=False,
                operation="index",
            ),
            folder_path="/p",
        )
        assert job.job_type == "documents"

    def test_job_type_can_be_set_to_git_history(self) -> None:
        """job_type can be set to 'git_history'."""
        job = JobRecord(
            id="job_y",
            job_type="git_history",
            dedupe_key=JobRecord.compute_git_dedupe_key("/repo"),
            folder_path="/repo",
            source="git",
        )
        assert job.job_type == "git_history"

    def test_old_serialized_record_without_job_type_loads_as_documents(
        self,
    ) -> None:
        """model_validate on a dict lacking 'job_type' defaults to 'documents'.

        This ensures backward-compat with persisted rows from before this field
        was added.
        """
        old_dict = {
            "id": "job_old",
            "dedupe_key": "abc123",
            "folder_path": "/some/path",
            "status": "done",
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
        job = JobRecord.model_validate(old_dict)
        assert job.job_type == "documents"

    def test_compute_git_dedupe_key_differs_from_doc_key(self) -> None:
        """git dedupe key must not collide with doc dedupe key for same path."""
        path = "/repo/project"
        doc_key = JobRecord.compute_dedupe_key(
            folder_path=path, include_code=False, operation="index"
        )
        git_key = JobRecord.compute_git_dedupe_key(path)
        assert doc_key != git_key

    def test_compute_git_dedupe_key_is_deterministic(self) -> None:
        """Same path produces same key."""
        k1 = JobRecord.compute_git_dedupe_key("/a/b/c")
        k2 = JobRecord.compute_git_dedupe_key("/a/b/c")
        assert k1 == k2

    def test_compute_git_dedupe_key_differs_by_path(self) -> None:
        """Different paths produce different keys."""
        k1 = JobRecord.compute_git_dedupe_key("/a/b")
        k2 = JobRecord.compute_git_dedupe_key("/a/c")
        assert k1 != k2


# ===========================================================================
# 2. JobWorker dispatch
# ===========================================================================


class TestJobWorkerGitDispatch:
    """JobWorker routes git_history jobs to _process_git_job."""

    @pytest.mark.asyncio
    async def test_git_job_done_on_zero_delta(self) -> None:
        """DONE when before==after (incremental reindex, no new commits)."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=10, count_after=10
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.DONE
        assert job.finished_at is not None
        mock_git_svc.index_repo.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_git_job_done_with_positive_delta(self) -> None:
        """DONE when count_after > count_before."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=5, count_after=15
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.DONE
        assert job.chunks_added == 10  # max(0, 15 - 5)

    @pytest.mark.asyncio
    async def test_git_job_chunks_added_max_zero(self) -> None:
        """chunks_added is max(0, after-before) — never negative."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=20, count_after=5  # store shrank (shouldn't happen but guard)
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.DONE
        assert job.chunks_added == 0

    @pytest.mark.asyncio
    async def test_git_job_failed_when_index_repo_raises(self) -> None:
        """FAILED status when index_repo raises."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=0, count_after=0
        )
        mock_git_svc.index_repo = AsyncMock(side_effect=RuntimeError("git boom"))
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.FAILED
        assert "git boom" in (job.error or "")
        assert job.finished_at is not None

    @pytest.mark.asyncio
    async def test_git_job_failed_when_service_not_set(self) -> None:
        """FAILED when git_index_service is None (misconfigured worker)."""
        worker, mock_store, _ = _make_worker_for_git()
        # Do NOT call set_git_service — service stays None

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.FAILED
        assert job.finished_at is not None
        assert job.error is not None
        assert "not configured" in job.error

    @pytest.mark.asyncio
    async def test_git_job_does_not_run_doc_pipeline(self) -> None:
        """_run_indexing_pipeline is NOT called for a git job."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=0, count_after=5
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )
        worker._indexing_service._run_indexing_pipeline = AsyncMock()

        job = _make_git_job()
        await worker._process_job(job)

        worker._indexing_service._run_indexing_pipeline.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_git_job_progress_set_to_100_on_done(self) -> None:
        """Progress reaches 100% when git job completes."""
        worker, mock_store, mock_git_svc = _make_worker_for_git(
            count_before=0, count_after=3
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.DONE
        assert job.progress is not None
        assert job.progress.percent == 100.0

    @pytest.mark.asyncio
    async def test_git_job_done_when_count_before_raises(self) -> None:
        """DONE even when storage.get_count raises on the BEFORE read.

        The guarded count_before path falls back to 0, so the job still
        completes successfully when index_repo succeeds.
        """
        import asyncio

        mock_storage = MagicMock()
        mock_storage.is_initialized = True
        # First get_count (before) raises; second (after) returns 5
        mock_storage.get_count = AsyncMock(side_effect=[RuntimeError("db error"), 5])

        mock_indexing_service = MagicMock()
        mock_indexing_service.storage_backend = mock_storage
        mock_indexing_service.get_status = AsyncMock(
            return_value={"total_chunks": 5, "total_documents": 1}
        )
        mock_indexing_service._lock = asyncio.Lock()

        mock_job_store = AsyncMock()
        mock_job_store.update_job = AsyncMock()

        mock_git_svc = AsyncMock()
        mock_git_svc.index_repo = AsyncMock(return_value={"commits_new": 3})

        worker = JobWorker(
            job_store=mock_job_store,
            indexing_service=mock_indexing_service,
        )
        worker.set_git_service(
            service=mock_git_svc,
            config=MagicMock(),
            project_root="/repo",
        )

        job = _make_git_job()
        await worker._process_job(job)

        assert job.status == JobStatus.DONE
        assert job.chunks_added >= 0


# ===========================================================================
# 3. Dedupe: enqueue_git_history_job
# ===========================================================================


class TestEnqueueGitHistoryJobDedupe:
    """Two enqueue calls while first PENDING → second is a no-op dedupe hit."""

    @pytest.mark.asyncio
    async def test_first_enqueue_creates_job(self, tmp_path: Path) -> None:
        store = JobQueueStore(tmp_path)
        await store.initialize()
        service = JobQueueService(store=store, project_root=None)

        resp = await service.enqueue_git_history_job(str(tmp_path))

        assert resp.dedupe_hit is False
        assert resp.job_id.startswith("job_")
        job = await store.get_job(resp.job_id)
        assert job is not None
        assert job.job_type == "git_history"
        assert job.source == "git"
        assert job.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_second_enqueue_while_pending_is_dedupe_hit(
        self, tmp_path: Path
    ) -> None:
        store = JobQueueStore(tmp_path)
        await store.initialize()
        service = JobQueueService(store=store, project_root=None)

        first = await service.enqueue_git_history_job(str(tmp_path))
        second = await service.enqueue_git_history_job(str(tmp_path))

        assert second.dedupe_hit is True
        assert second.job_id == first.job_id

    @pytest.mark.asyncio
    async def test_queue_length_unchanged_on_dedupe(self, tmp_path: Path) -> None:
        store = JobQueueStore(tmp_path)
        await store.initialize()
        service = JobQueueService(store=store, project_root=None)

        await service.enqueue_git_history_job(str(tmp_path))
        first_len = await store.get_queue_length()
        await service.enqueue_git_history_job(str(tmp_path))
        second_len = await store.get_queue_length()

        assert first_len == second_len

    @pytest.mark.asyncio
    async def test_different_paths_get_different_jobs(self, tmp_path: Path) -> None:
        store = JobQueueStore(tmp_path)
        await store.initialize()
        service = JobQueueService(store=store, project_root=None)

        path_a = str(tmp_path / "a")
        path_b = str(tmp_path / "b")

        r1 = await service.enqueue_git_history_job(path_a)
        r2 = await service.enqueue_git_history_job(path_b)

        assert r1.dedupe_hit is False
        assert r2.dedupe_hit is False
        assert r1.job_id != r2.job_id
