"""Read-only gate: SKIPPED status exists; any embed-producing job ends SKIPPED."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.models.job import JobRecord, JobStatus


def test_skipped_status_exists():
    assert JobStatus.SKIPPED.value == "skipped"


@pytest.mark.asyncio
async def test_read_only_job_is_skipped(monkeypatch):
    from brainpalace_server.job_queue import job_worker as jw

    monkeypatch.setattr(jw, "is_read_only", lambda: True)

    indexing_service = MagicMock()
    job_store = MagicMock()
    job_store.update_job = AsyncMock()

    worker = jw.JobWorker(job_store=job_store, indexing_service=indexing_service)
    job = JobRecord(
        id="job_test",
        dedupe_key="k",
        folder_path="/tmp/x",
        job_type="documents",
        status=JobStatus.PENDING,
    )

    await worker._process_job(job)

    assert job.status == JobStatus.SKIPPED
    assert "read-only" in (job.error or "").lower()
    job_store.update_job.assert_awaited()
    indexing_service._run_indexing_pipeline.assert_not_called()
