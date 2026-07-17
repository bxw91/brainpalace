"""Fix 7 (A12) — cancel_job on a BLOCKED job cancels immediately.

Before this fix, cancel_job had no BLOCKED branch and fell through to the
"unexpected status" no-op return — combined with dedupe matching BLOCKED,
a budget-blocked job was a hard stuck state with no manual escape hatch.
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
async def test_cancel_blocked_job_cancels_immediately(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    result = await service.cancel_job(job_id)
    assert result["status"] == "cancelled"
    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.CANCELLED
    assert job.finished_at is not None
