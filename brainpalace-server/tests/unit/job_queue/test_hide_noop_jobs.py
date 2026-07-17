"""Fix 4 (A6/A8) — no-op completed jobs are hidden from the default listing.

A no-op job (status=done, chunks_added=0, chunks_removed=0, error=None -- a
re-index that found nothing changed) costs history without adding any: it's
paginated out a real job. `get_all_jobs`/`list_jobs` filter it before the
pagination slice (D10) so pages stay full; `include_noop=True` (CLI `--all`,
dashboard `?all=1`) reveals it. Counts (`QueueStats`/`completed`) stay whole —
only the row list is filtered (D10's "leave counts whole" call).
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import jobs as jobs_router
from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.job import JobRecord, JobStatus


def _record(
    job_id: str,
    *,
    status: JobStatus,
    chunks_added: int = 0,
    chunks_removed: int = 0,
    error: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        dedupe_key=f"key-{job_id}",
        folder_path="/tmp/x",
        status=status,
        chunks_added=chunks_added,
        chunks_removed=chunks_removed,
        error=error,
        enqueued_at=datetime.now(timezone.utc),
    )


async def _seeded_store(tmp_path: Path) -> JobQueueStore:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    await store.append_job(_record("job_noop", status=JobStatus.DONE))
    await store.append_job(_record("job_delta", status=JobStatus.DONE, chunks_added=12))
    await store.append_job(_record("job_failed", status=JobStatus.FAILED, error="x"))
    await store.append_job(_record("job_blocked", status=JobStatus.BLOCKED))
    await store.append_job(_record("job_running", status=JobStatus.RUNNING))
    await store.append_job(_record("job_pending", status=JobStatus.PENDING))
    return store


@pytest.mark.asyncio
async def test_get_all_jobs_hides_noop_done_by_default(tmp_path: Path) -> None:
    store = await _seeded_store(tmp_path)
    ids = {j.id for j in await store.get_all_jobs()}
    assert "job_noop" not in ids
    assert ids == {
        "job_delta",
        "job_failed",
        "job_blocked",
        "job_running",
        "job_pending",
    }


@pytest.mark.asyncio
async def test_get_all_jobs_reveals_noop_with_include_noop(tmp_path: Path) -> None:
    store = await _seeded_store(tmp_path)
    ids = {j.id for j in await store.get_all_jobs(include_noop=True)}
    assert "job_noop" in ids
    assert len(ids) == 6


@pytest.mark.asyncio
async def test_count_noop_jobs(tmp_path: Path) -> None:
    store = await _seeded_store(tmp_path)
    assert await store.count_noop_jobs() == 1


@pytest.mark.asyncio
async def test_list_jobs_reports_noop_hidden_and_whole_counts(tmp_path: Path) -> None:
    store = await _seeded_store(tmp_path)
    service = JobQueueService(store, project_root=tmp_path)

    default_resp = await service.list_jobs()
    assert default_resp.noop_hidden == 1
    assert "job_noop" not in {j.id for j in default_resp.jobs}
    # Counts stay whole (D10) -- completed includes the hidden no-op job.
    assert default_resp.completed == 2  # job_delta + job_noop

    all_resp = await service.list_jobs(include_noop=True)
    assert all_resp.noop_hidden == 0
    assert "job_noop" in {j.id for j in all_resp.jobs}
    assert all_resp.completed == 2


@pytest.mark.asyncio
async def test_endpoint_all_query_param_reveals_noop(tmp_path: Path) -> None:
    store = await _seeded_store(tmp_path)
    service = JobQueueService(store, project_root=tmp_path)
    app = FastAPI()
    app.include_router(jobs_router.router, prefix="/index/jobs")
    app.state.job_service = service
    client = TestClient(app)

    default_ids = {j["id"] for j in client.get("/index/jobs/").json()["jobs"]}
    assert "job_noop" not in default_ids

    all_ids = {j["id"] for j in client.get("/index/jobs/?all=1").json()["jobs"]}
    assert "job_noop" in all_ids
