"""BLOCKED job state + enriched BudgetExceededError (pause+approve design)."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.job_queue.job_worker import JobWorker
from brainpalace_server.models.index import IndexingStatusEnum, IndexRequest
from brainpalace_server.models.job import (
    JobDetailResponse,
    JobRecord,
    JobStatus,
    JobSummary,
)
from brainpalace_server.services.indexing_service import (
    BudgetExceededError,
    enforce_token_budget,
)


class _Chunk:
    def __init__(self, text: str) -> None:
        self.text = text


def test_budget_error_carries_numbers() -> None:
    with pytest.raises(BudgetExceededError) as exc_info:
        enforce_token_budget([_Chunk("x" * 4000)], limit=100, force=False)
    err = exc_info.value
    assert err.estimated_tokens == 1000
    assert err.limit == 100
    assert "100" in str(err)


def test_blocked_status_exists() -> None:
    assert JobStatus.BLOCKED.value == "blocked"
    assert IndexingStatusEnum.BLOCKED.value == "blocked"


def _record(**overrides) -> JobRecord:
    base = {
        "id": "job_abc123def456",
        "dedupe_key": JobRecord.compute_dedupe_key(
            folder_path="/tmp/p", include_code=False, operation="index"
        ),
        "folder_path": "/tmp/p",
    }
    base.update(overrides)
    return JobRecord(**base)


def test_job_record_new_fields_default_and_persist() -> None:
    job = _record()
    assert job.force_budget is False
    assert job.budget_info is None
    blocked = _record(
        status=JobStatus.BLOCKED,
        budget_info={"estimated_tokens": 412_000, "limit": 100_000},
        force_budget=True,
    )
    # JSONL round-trip (the store persists via model_dump_json / model_validate_json)
    reread = JobRecord.model_validate_json(blocked.model_dump_json())
    assert reread.status is JobStatus.BLOCKED
    assert reread.budget_info == {"estimated_tokens": 412_000, "limit": 100_000}
    assert reread.force_budget is True


def test_summary_and_detail_carry_budget_info() -> None:
    blocked = _record(
        status=JobStatus.BLOCKED,
        budget_info={"estimated_tokens": 5, "limit": 1},
    )
    assert JobSummary.from_record(blocked).budget_info == blocked.budget_info
    assert JobDetailResponse.from_record(blocked).budget_info == blocked.budget_info


@pytest.mark.asyncio
async def test_force_budget_survives_enqueue(tmp_path: Path) -> None:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    resp = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path), force_budget=True),
        allow_external=True,
    )
    job = await store.get_job(resp.job_id)
    assert job is not None
    assert job.force_budget is True


@pytest.mark.asyncio
async def test_worker_parks_over_budget_job_as_blocked(tmp_path: Path) -> None:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()

    indexing_service = MagicMock()
    indexing_service._lock = asyncio.Lock()  # real lock — worker uses `async with`
    indexing_service._run_indexing_pipeline = AsyncMock(
        side_effect=BudgetExceededError(
            "over budget", estimated_tokens=412_000, limit=100_000
        )
    )
    # (the count-before block wraps storage access in try/except — the bare
    # MagicMock storage_backend raising on `await` is swallowed there;
    # BudgetExceededError from the pipeline escapes the inner try, which only
    # catches asyncio.TimeoutError — job_worker.py:475-505)

    worker = JobWorker(job_store=store, indexing_service=indexing_service)

    job = _record(status=JobStatus.RUNNING, started_at=datetime.now(timezone.utc))
    await store.append_job(job)

    await worker._process_job(job)

    assert job.status is JobStatus.BLOCKED
    assert job.budget_info == {"estimated_tokens": 412_000, "limit": 100_000}
    assert job.finished_at is None
    assert "--approve" in (job.error or "")
    assert job.id in (job.error or "")


@pytest.mark.asyncio
async def test_watch_trigger_coalesces_into_blocked_job(tmp_path: Path) -> None:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)

    first = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path)), allow_external=True
    )
    job = await store.get_job(first.job_id)
    job.status = JobStatus.BLOCKED
    await store.update_job(job)

    # a watch=auto file change re-enqueues the same folder → must dedupe-hit
    second = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path)), allow_external=True, source="watch"
    )
    assert second.dedupe_hit is True
    assert second.job_id == first.job_id

    # blocked jobs are NOT pending — the worker loop must not pick them up
    assert all(j.id != job.id for j in await store.get_pending_jobs())
    assert [j.id for j in await store.get_blocked_jobs()] == [job.id]


@pytest.mark.asyncio
async def test_blocked_counts_in_list_and_stats(tmp_path: Path) -> None:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    resp = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path)), allow_external=True
    )
    job = await store.get_job(resp.job_id)
    job.status = JobStatus.BLOCKED
    await store.update_job(job)

    listing = await service.list_jobs()
    assert listing.blocked == 1
    stats = await service.get_queue_stats()
    assert stats.blocked == 1
