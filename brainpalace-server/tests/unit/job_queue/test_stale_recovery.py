"""Tests for JobQueueStore stale-job recovery returning handled records (D14)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.job import JobRecord, JobStatus


def _make_job(
    job_id: str,
    folder: str = "/tmp/test",
    status: JobStatus = JobStatus.PENDING,
    retry_count: int = 0,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        dedupe_key=JobRecord.compute_dedupe_key(
            folder_path=folder, include_code=False, operation="index"
        ),
        folder_path=folder,
        status=status,
        retry_count=retry_count,
        started_at=datetime.now(timezone.utc) if status == JobStatus.RUNNING else None,
    )


@pytest.mark.asyncio
async def test_initialize_returns_empty_when_no_stale_jobs(tmp_path: Path) -> None:
    store = JobQueueStore(tmp_path)
    stale = await store.initialize()
    assert stale == []


@pytest.mark.asyncio
async def test_initialize_returns_stale_running_job_reset_to_pending(
    tmp_path: Path,
) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    job = _make_job("job_a", folder="/p/a", status=JobStatus.RUNNING, retry_count=0)
    await store.append_job(job)

    store2 = JobQueueStore(tmp_path)
    stale = await store2.initialize()

    assert len(stale) == 1
    assert stale[0].id == "job_a"
    assert stale[0].folder_path == "/p/a"
    assert stale[0].status == JobStatus.PENDING
    assert stale[0].retry_count == 1


@pytest.mark.asyncio
async def test_initialize_returns_stale_running_job_failed_after_max_retries(
    tmp_path: Path,
) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    job = _make_job(
        "job_b",
        folder="/p/b",
        status=JobStatus.RUNNING,
        retry_count=JobQueueStore.MAX_RETRIES,
    )
    await store.append_job(job)

    store2 = JobQueueStore(tmp_path)
    stale = await store2.initialize()

    assert len(stale) == 1
    assert stale[0].id == "job_b"
    assert stale[0].status == JobStatus.FAILED
    assert stale[0].retry_count == JobQueueStore.MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_initialize_returns_multiple_stale_jobs_same_folder(
    tmp_path: Path,
) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    for jid in ("job_c1", "job_c2"):
        await store.append_job(
            _make_job(jid, folder="/p/c", status=JobStatus.RUNNING, retry_count=0)
        )

    store2 = JobQueueStore(tmp_path)
    stale = await store2.initialize()

    assert len(stale) == 2
    assert {j.folder_path for j in stale} == {"/p/c"}


@pytest.mark.asyncio
async def test_initialize_ignores_already_done_or_pending(tmp_path: Path) -> None:
    store = JobQueueStore(tmp_path)
    await store.initialize()
    await store.append_job(_make_job("job_d1", folder="/p/d", status=JobStatus.DONE))
    await store.append_job(_make_job("job_d2", folder="/p/d", status=JobStatus.PENDING))
    await store.append_job(
        _make_job("job_d3", folder="/p/e", status=JobStatus.RUNNING, retry_count=0)
    )

    store2 = JobQueueStore(tmp_path)
    stale = await store2.initialize()

    # Only the RUNNING job is stale; DONE + PENDING are not.
    assert [j.id for j in stale] == ["job_d3"]
