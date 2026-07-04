"""Phase 5 — per-job embedding token budget guard tests."""

import pytest

from brainpalace_server.services.indexing_service import (
    BudgetExceededError,
    estimate_chunk_tokens,
)


def test_estimate_chunk_tokens_sums_chunk_text():
    class C:
        def __init__(self, t):
            self.text = t

    assert estimate_chunk_tokens([C("a" * 8), C("b" * 8)]) >= 2  # chars/4 floor


def test_budget_guard_raises_over_limit():
    class C:
        text = "x" * 4000  # ~1000 tokens

    with pytest.raises(BudgetExceededError):
        from brainpalace_server.services.indexing_service import enforce_token_budget

        enforce_token_budget([C(), C(), C()], limit=1000, force=False)


def test_budget_guard_allows_when_forced():
    class C:
        text = "x" * 4000

    from brainpalace_server.services.indexing_service import enforce_token_budget

    enforce_token_budget([C()], limit=1, force=True)  # no raise


def test_budget_guard_disabled_when_limit_zero():
    class C:
        text = "x" * 40000  # huge

    from brainpalace_server.services.indexing_service import enforce_token_budget

    # limit=0 disables the guard — should not raise
    enforce_token_budget([C(), C(), C()], limit=0, force=False)


def test_budget_guard_raises_with_message():
    class C:
        text = "x" * 4000  # ~1000 tokens each

    from brainpalace_server.services.indexing_service import enforce_token_budget

    with pytest.raises(BudgetExceededError, match="force_budget"):
        enforce_token_budget([C(), C()], limit=500, force=False)


def test_estimate_returns_total():
    class C:
        def __init__(self, t):
            self.text = t

    result = estimate_chunk_tokens([C("a" * 400)])  # 400 chars = 100 tokens
    assert result == 100


def test_enforce_returns_token_total():
    class C:
        text = "a" * 400  # 100 tokens

    from brainpalace_server.services.indexing_service import enforce_token_budget

    total = enforce_token_budget([C()], limit=200, force=False)
    assert total == 100


def test_budget_guard_allows_exactly_at_limit():
    """Chunks that exactly equal the limit should NOT raise."""

    class C:
        text = "a" * 400  # 100 tokens

    from brainpalace_server.services.indexing_service import enforce_token_budget

    # 1 chunk * 100 tokens = 100, limit=100 — should not raise (equal, not over)
    enforce_token_budget([C()], limit=100, force=False)


def test_job_worker_parks_budget_error_as_blocked_job():
    """BudgetExceededError flows through the worker's except and PARKS the job as
    BLOCKED (pause+approve design) instead of failing it terminally."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from brainpalace_server.job_queue.job_worker import JobWorker
    from brainpalace_server.models.job import JobRecord, JobStatus

    job = JobRecord(
        id="test-budget-job",
        dedupe_key="deadbeef",
        folder_path="/tmp/fake",
        status=JobStatus.PENDING,
        include_code=False,
        chunk_size=512,
        chunk_overlap=50,
        recursive=True,
        force=False,
    )

    mock_job_store = AsyncMock()
    mock_job_store.get_job = AsyncMock(return_value=job)
    mock_job_store.update_job = AsyncMock()

    mock_indexing_service = MagicMock()
    mock_indexing_service._lock = asyncio.Lock()
    mock_indexing_service.storage_backend = MagicMock()
    mock_indexing_service.storage_backend.is_initialized = False

    budget_error = BudgetExceededError(
        "Index would embed ~5,000 tokens, over the budget of 1,000. "
        "Raise indexing.max_embed_tokens_per_job or re-run with force_budget=true.",
        estimated_tokens=5000,
        limit=1000,
    )
    mock_indexing_service._run_indexing_pipeline = AsyncMock(side_effect=budget_error)

    worker = JobWorker(mock_job_store, mock_indexing_service)

    asyncio.get_event_loop().run_until_complete(worker._process_job(job))

    assert job.status == JobStatus.BLOCKED
    assert job.budget_info == {"estimated_tokens": 5000, "limit": 1000}
    assert job.finished_at is None
    assert "--approve" in (job.error or "")
