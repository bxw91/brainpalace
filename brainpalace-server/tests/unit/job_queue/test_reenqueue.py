"""Tests for JobQueueService.reenqueue_from_record (D14 helper)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.job import JobRecord, JobStatus


def _make_record(
    folder: str,
    status: JobStatus = JobStatus.FAILED,
    *,
    include_code: bool = False,
    operation: str = "index",
    chunk_size: int = 512,
    recursive: bool = True,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> JobRecord:
    return JobRecord(
        id="job_orig",
        dedupe_key=JobRecord.compute_dedupe_key(
            folder_path=folder,
            include_code=include_code,
            operation=operation,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        ),
        folder_path=folder,
        include_code=include_code,
        operation=operation,
        chunk_size=chunk_size,
        recursive=recursive,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        status=status,
        retry_count=4,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        error="max retries exceeded",
    )


@pytest.mark.asyncio
async def test_reenqueue_creates_new_job_when_no_active_match(
    tmp_path: Path,
) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    service = JobQueueService(store=store, project_root=None)

    record = _make_record("/p/x", status=JobStatus.FAILED)
    resp = await service.reenqueue_from_record(record)

    assert resp.dedupe_hit is False
    assert resp.job_id != record.id
    requeued = await store.get_job(resp.job_id)
    assert requeued is not None
    assert requeued.folder_path == "/p/x"
    assert requeued.status == JobStatus.PENDING
    assert requeued.source == "auto"


@pytest.mark.asyncio
async def test_reenqueue_dedupes_against_active_job(tmp_path: Path) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    service = JobQueueService(store=store, project_root=None)

    # First: a regular job exists in PENDING state for the folder.
    record = _make_record("/p/y", status=JobStatus.PENDING)
    first = await service.reenqueue_from_record(record)
    assert first.dedupe_hit is False

    # Second re-enqueue: should dedupe to the first.
    second = await service.reenqueue_from_record(record)
    assert second.dedupe_hit is True
    assert second.job_id == first.job_id


@pytest.mark.asyncio
async def test_reenqueue_preserves_index_params(tmp_path: Path) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    service = JobQueueService(store=store, project_root=None)

    record = _make_record(
        "/p/z",
        status=JobStatus.FAILED,
        include_code=True,
        chunk_size=1024,
        recursive=False,
        include_patterns=["*.py"],
        exclude_patterns=["build/**"],
    )
    resp = await service.reenqueue_from_record(record)
    new_job = await store.get_job(resp.job_id)

    assert new_job is not None
    assert new_job.include_code is True
    assert new_job.chunk_size == 1024
    assert new_job.recursive is False
    assert new_job.include_patterns == ["*.py"]
    assert new_job.exclude_patterns == ["build/**"]


@pytest.mark.asyncio
async def test_reenqueue_sets_source_auto(tmp_path: Path) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    service = JobQueueService(store=store, project_root=None)

    record = _make_record("/p/w", status=JobStatus.FAILED)
    resp = await service.reenqueue_from_record(record)
    new_job = await store.get_job(resp.job_id)

    assert new_job is not None
    assert new_job.source == "auto"
