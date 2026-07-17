"""Fix 2 (A14) — job_service.revalidate_blocked_job(job_id).

Mirrors approve_job (test_approve_job.py) but keeps force_budget=False —
this is the reaper's resume path (D4/D5): re-run the budget guard on fresh
disk rather than bypass it, and flip the record in place (same id).
"""

from pathlib import Path

import pytest

from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.index import IndexRequest
from brainpalace_server.models.job import JobStatus


async def _blocked_service(tmp_path: Path) -> tuple[JobQueueService, str]:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    resp = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path)), allow_external=True
    )
    job = await store.get_job(resp.job_id)
    job.status = JobStatus.BLOCKED
    job.error = "Indexing paused"
    job.budget_info = {"estimated_tokens": 5, "limit": 1}
    await store.update_job(job)
    return service, resp.job_id


@pytest.mark.asyncio
async def test_revalidate_flips_blocked_to_pending_without_force(
    tmp_path: Path,
) -> None:
    service, job_id = await _blocked_service(tmp_path)
    result = await service.revalidate_blocked_job(job_id)
    assert result["status"] == "pending"
    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.PENDING
    assert job.force_budget is False  # revalidation, not a bypass (D4)
    assert job.error is None
    assert job.budget_info == {"estimated_tokens": 5, "limit": 1}  # kept for display


@pytest.mark.asyncio
async def test_revalidate_rejects_non_blocked_and_unknown(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    await service.revalidate_blocked_job(job_id)  # now PENDING
    with pytest.raises(ValueError):
        await service.revalidate_blocked_job(job_id)
    with pytest.raises(KeyError):
        await service.revalidate_blocked_job("job_missing000")
