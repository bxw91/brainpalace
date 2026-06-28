"""Snapshot compaction must bound growth: strip the heavy eviction_summary
from terminal jobs and cap how many terminal jobs are retained."""

import pytest

from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.job import JobRecord, JobStatus


def _job(job_id: str, status: JobStatus, with_eviction: bool = True) -> JobRecord:
    return JobRecord(
        id=job_id,
        dedupe_key=job_id,
        folder_path="/repo",
        status=status,
        eviction_summary=(
            {"files_added": ["a.py", "b.py"], "files_unchanged": ["c.py"]}
            if with_eviction
            else None
        ),
    )


@pytest.mark.asyncio
async def test_compact_strips_eviction_summary_from_terminal_jobs(tmp_path):
    store = JobQueueStore(tmp_path)
    await store.append_job(_job("job_done", JobStatus.DONE))
    await store.append_job(_job("job_pending", JobStatus.PENDING))

    await store._compact()

    done = await store.get_job("job_done")
    pending = await store.get_job("job_pending")
    assert done.eviction_summary is None, "terminal job must shed its eviction_summary"
    assert pending.eviction_summary is not None, "active job keeps eviction_summary"


@pytest.mark.asyncio
async def test_compact_caps_retained_terminal_jobs(tmp_path):
    store = JobQueueStore(tmp_path)
    cap = JobQueueStore.MAX_TERMINAL_JOBS
    for i in range(cap + 50):
        await store.append_job(_job(f"job_done_{i:04d}", JobStatus.DONE))
    await store.append_job(_job("job_pending", JobStatus.PENDING))

    await store._compact()

    stats = await store.get_queue_stats()
    assert stats.completed == cap, f"expected {cap} retained terminal jobs"
    # The active job is always retained regardless of the cap.
    assert await store.get_job("job_pending") is not None
    # The oldest terminal job is evicted; the newest survives.
    assert await store.get_job("job_done_0000") is None
    assert await store.get_job(f"job_done_{cap + 49:04d}") is not None
