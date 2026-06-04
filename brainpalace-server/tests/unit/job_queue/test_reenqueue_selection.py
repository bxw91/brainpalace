"""Tests for select_reenqueue_candidates (D14 poison-job loop guard).

Regression: a stale RUNNING job that deterministically crashes the server
(e.g. a native segfault in the vector store) is reset on restart and re-run.
After the retry budget is exhausted it is marked FAILED — but the D14
auto-reindex loop used to re-enqueue *every* stale job, including FAILED ones,
minting a fresh retry_count=0 job and defeating the retry cap. That turned a
single crash into an infinite crash-loop. select_reenqueue_candidates must
exclude permanently-FAILED stale jobs.
"""

from datetime import datetime, timezone

from brainpalace_server.job_queue.job_store import select_reenqueue_candidates
from brainpalace_server.models.job import JobRecord, JobStatus


def _rec(
    job_id: str,
    folder: str,
    status: JobStatus,
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
        started_at=datetime.now(timezone.utc),
    )


def test_failed_jobs_are_excluded() -> None:
    """Permanently-FAILED stale jobs must NOT be re-enqueued (poison guard)."""
    stale = [_rec("j1", "/p/a", JobStatus.FAILED, retry_count=4)]
    assert select_reenqueue_candidates(stale) == []


def test_reset_pending_jobs_are_included() -> None:
    """Jobs reset to PENDING (still under retry cap) are re-enqueued."""
    stale = [_rec("j1", "/p/a", JobStatus.PENDING, retry_count=1)]
    picked = select_reenqueue_candidates(stale)
    assert [j.id for j in picked] == ["j1"]


def test_dedupes_by_folder() -> None:
    """One re-enqueue per folder even with multiple reset jobs."""
    stale = [
        _rec("j1", "/p/a", JobStatus.PENDING),
        _rec("j2", "/p/a", JobStatus.PENDING),
        _rec("j3", "/p/b", JobStatus.PENDING),
    ]
    picked = select_reenqueue_candidates(stale)
    assert {j.folder_path for j in picked} == {"/p/a", "/p/b"}
    assert len(picked) == 2


def test_mixed_failed_and_pending_same_folder_includes_pending() -> None:
    """A folder with both a FAILED and a reset job still gets re-enqueued."""
    stale = [
        _rec("j_failed", "/p/a", JobStatus.FAILED, retry_count=4),
        _rec("j_reset", "/p/a", JobStatus.PENDING, retry_count=1),
    ]
    picked = select_reenqueue_candidates(stale)
    assert [j.id for j in picked] == ["j_reset"]


def test_folder_with_only_failed_job_excluded() -> None:
    """The poison case: folder whose only stale job exhausted retries."""
    stale = [_rec("j_failed", "/p/poison", JobStatus.FAILED, retry_count=4)]
    assert select_reenqueue_candidates(stale) == []


def test_empty_input() -> None:
    assert select_reenqueue_candidates([]) == []
