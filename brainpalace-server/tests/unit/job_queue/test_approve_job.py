"""approve_job service + POST /index/jobs/{job_id}/approve router."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers import jobs as jobs_router
from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.index import IndexRequest
from brainpalace_server.models.job import JobStatus
from brainpalace_server.models.query import BlockedJobInfo, QueryResponse


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
async def test_approve_flips_blocked_to_pending_with_force(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    result = await service.approve_job(job_id)
    assert result["status"] == "pending"
    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.PENDING
    assert job.force_budget is True
    assert job.error is None
    assert job.budget_info == {"estimated_tokens": 5, "limit": 1}  # kept for display


@pytest.mark.asyncio
async def test_approve_rejects_non_blocked_and_unknown(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    await service.approve_job(job_id)  # now PENDING
    with pytest.raises(ValueError):
        await service.approve_job(job_id)
    with pytest.raises(KeyError):
        await service.approve_job("job_missing000")


@pytest.mark.asyncio
async def test_approve_endpoint_status_codes(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    app = FastAPI()
    app.include_router(jobs_router.router, prefix="/index/jobs")
    app.state.job_service = service
    client = TestClient(app)

    ok = client.post(f"/index/jobs/{job_id}/approve")
    assert ok.status_code == 200
    assert ok.json()["status"] == "pending"
    assert client.post(f"/index/jobs/{job_id}/approve").status_code == 409
    assert client.post("/index/jobs/job_missing000/approve").status_code == 404


@pytest.mark.asyncio
async def test_get_blocked_summary_newest_wins_and_shape(tmp_path: Path) -> None:
    service, job_id = await _blocked_service(tmp_path)
    summary = await service.get_blocked_summary()
    assert summary is not None
    assert summary["job_id"] == job_id
    assert summary["folder_path"] == str(tmp_path)
    assert summary["estimated_tokens"] == 5
    assert summary["limit"] == 1
    assert isinstance(summary["blocked_since"], str)
    # model accepts the dict verbatim
    info = BlockedJobInfo(**summary)
    assert info.job_id == job_id
    # attachable to a QueryResponse
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    assert resp.index_blocked is None
    resp.index_blocked = info
    assert "index_blocked" in resp.model_dump()


@pytest.mark.asyncio
async def test_get_blocked_summary_none_when_no_blocked(tmp_path: Path) -> None:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    assert await service.get_blocked_summary() is None
