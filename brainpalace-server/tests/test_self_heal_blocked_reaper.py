"""Fix 2 — the blocked-job reaper (`_reap_blocked_jobs`, wired into `heal_once`).

A budget-BLOCKED job whose bloat source later shrinks/vanishes must revalidate
against current disk and either resume (now under cap) or dismiss (nothing
left), on the heartbeat. Covers the plan-of-record test matrix (a)-(g):

(a) no change signal since blocked_since -> NOT re-queued (D6)
(b) change signal present -> flipped to PENDING, force_budget=False (D4/D5)
(c) different-params active job for folder -> blocked one dismissed (D6b-ii)
(d) any job RUNNING -> whole pass skipped (D6b-i)
(e) read-only -> whole pass skipped (D6d)
(f) folder_path missing on disk -> blocked job dismissed (D6e)
(g) re-block advances started_at so an unchanged folder won't re-fire (D6c)
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import brainpalace_server.self_heal as sh
from brainpalace_server.job_queue.job_service import JobQueueService
from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.index import IndexRequest
from brainpalace_server.models.job import JobRecord, JobStatus


async def _make_blocked(
    tmp_path: Path,
    *,
    blocked_since: datetime,
    include_code: bool = False,
) -> tuple[JobQueueService, str]:
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    resp = await service.enqueue_job(
        IndexRequest(folder_path=str(tmp_path), include_code=include_code),
        allow_external=True,
    )
    job = await store.get_job(resp.job_id)
    job.status = JobStatus.BLOCKED
    job.error = "Indexing paused"
    job.budget_info = {"estimated_tokens": 5, "limit": 1}
    job.started_at = blocked_since
    await store.update_job(job)
    return service, resp.job_id


def _app(job_service: JobQueueService, watcher: object | None) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(job_service=job_service, file_watcher_service=watcher)
    )


@pytest.mark.asyncio
async def test_no_change_signal_not_requeued(tmp_path: Path) -> None:
    """(a) No watcher change and folder mtime predates blocked_since -> left BLOCKED."""
    future_block = datetime.now(timezone.utc) + timedelta(hours=1)
    service, job_id = await _make_blocked(tmp_path, blocked_since=future_block)

    watcher = MagicMock()
    watcher.last_change_at.return_value = None

    await sh._reap_blocked_jobs(_app(service, watcher))

    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.BLOCKED


@pytest.mark.asyncio
async def test_change_signal_flips_to_pending_without_force(tmp_path: Path) -> None:
    """(b) A watcher change after blocked_since -> revalidated (PENDING, no force)."""
    past_block = datetime.now(timezone.utc) - timedelta(hours=1)
    service, job_id = await _make_blocked(tmp_path, blocked_since=past_block)

    watcher = MagicMock()
    watcher.last_change_at.return_value = datetime.now(timezone.utc)

    await sh._reap_blocked_jobs(_app(service, watcher))

    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.PENDING
    assert job.force_budget is False


@pytest.mark.asyncio
async def test_duplicate_dedupe_key_active_job_dismisses_blocked(
    tmp_path: Path,
) -> None:
    """(c) find_by_dedupe_key(job.dedupe_key) resolving to a DIFFERENT, active
    record (a genuine corner -- normally impossible since dedupe matches
    BLOCKED too, so a same-key job would have collapsed into this one) ->
    the stale blocked duplicate is dismissed, not re-queued.

    find_by_dedupe_key returns the FIRST matching record in insertion order,
    so the competitor must be appended *before* the blocked job to be the one
    returned (mirroring the only order in which two same-key active records
    could ever coexist).
    """
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)

    shared_key = "shared-dedupe-key-for-test"
    competitor = JobRecord(
        id="job_competitor01",
        dedupe_key=shared_key,
        folder_path=str(tmp_path),
        status=JobStatus.PENDING,
    )
    await store.append_job(competitor)

    past_block = datetime.now(timezone.utc) - timedelta(hours=1)
    blocked_job = JobRecord(
        id="job_blocked01",
        dedupe_key=shared_key,
        folder_path=str(tmp_path),
        status=JobStatus.BLOCKED,
        started_at=past_block,
    )
    await store.append_job(blocked_job)

    watcher = MagicMock()
    watcher.last_change_at.return_value = datetime.now(timezone.utc)

    await sh._reap_blocked_jobs(_app(service, watcher))

    job = await service.store.get_job(blocked_job.id)
    assert job.status is JobStatus.CANCELLED
    other = await service.store.get_job(competitor.id)
    assert other.status is JobStatus.PENDING  # untouched


@pytest.mark.asyncio
async def test_running_job_skips_whole_pass(tmp_path: Path) -> None:
    """(d) Any RUNNING job anywhere -> the whole reap pass is skipped."""
    past_block = datetime.now(timezone.utc) - timedelta(hours=1)
    service, job_id = await _make_blocked(tmp_path, blocked_since=past_block)

    # A second, unrelated job is RUNNING.
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    resp2 = await service.enqueue_job(
        IndexRequest(folder_path=str(other_dir)), allow_external=True
    )
    running = await service.store.get_job(resp2.job_id)
    running.status = JobStatus.RUNNING
    await service.store.update_job(running)

    watcher = MagicMock()
    watcher.last_change_at.return_value = datetime.now(timezone.utc)

    await sh._reap_blocked_jobs(_app(service, watcher))

    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.BLOCKED  # untouched -- pass was skipped


@pytest.mark.asyncio
async def test_read_only_skips_whole_pass(tmp_path: Path, monkeypatch) -> None:
    """(e) Read-only mode -> the whole reap pass is skipped (no writes)."""
    monkeypatch.setattr(sh, "is_read_only", lambda: True)
    past_block = datetime.now(timezone.utc) - timedelta(hours=1)
    service, job_id = await _make_blocked(tmp_path, blocked_since=past_block)

    watcher = MagicMock()
    watcher.last_change_at.return_value = datetime.now(timezone.utc)

    await sh._reap_blocked_jobs(_app(service, watcher))

    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.BLOCKED


@pytest.mark.asyncio
async def test_missing_folder_dismisses_blocked_job(tmp_path: Path) -> None:
    """(f) folder_path no longer exists on disk -> blocked job dismissed."""
    past_block = datetime.now(timezone.utc) - timedelta(hours=1)
    victim = tmp_path / "victim"
    victim.mkdir()
    store = JobQueueStore(state_dir=tmp_path)
    await store.initialize()
    service = JobQueueService(store, project_root=tmp_path)
    resp = await service.enqueue_job(
        IndexRequest(folder_path=str(victim)), allow_external=True
    )
    job = await store.get_job(resp.job_id)
    job.status = JobStatus.BLOCKED
    job.started_at = past_block
    await store.update_job(job)

    shutil.rmtree(victim)  # the indexed folder itself is gone

    watcher = MagicMock()
    watcher.last_change_at.return_value = None

    await sh._reap_blocked_jobs(_app(service, watcher))

    reread = await service.store.get_job(resp.job_id)
    assert reread.status is JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_reblock_advances_started_at_prevents_refire(tmp_path: Path) -> None:
    """(g) After a revalidate + re-block, the SAME stale change signal must not
    re-fire -- blocked_since (= started_at) has advanced past it (D6c)."""
    past_block = datetime.now(timezone.utc) - timedelta(hours=2)
    service, job_id = await _make_blocked(tmp_path, blocked_since=past_block)

    stale_change = datetime.now(timezone.utc) - timedelta(hours=1)  # > past_block
    watcher = MagicMock()
    watcher.last_change_at.return_value = stale_change

    await sh._reap_blocked_jobs(_app(service, watcher))
    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.PENDING  # first pass: revalidated

    # Simulate the worker running and re-blocking (started_at advances past
    # the stale change signal, per D6c).
    job.status = JobStatus.BLOCKED
    job.started_at = datetime.now(timezone.utc)
    await service.store.update_job(job)

    await sh._reap_blocked_jobs(_app(service, watcher))  # same stale watcher signal
    job = await service.store.get_job(job_id)
    assert job.status is JobStatus.BLOCKED  # not re-fired
