import pytest

from brainpalace_server.job_queue.job_store import JobQueueStore
from brainpalace_server.models.job import JobRecord, JobStatus
from brainpalace_server.rehome.detect import prefix_swap


@pytest.mark.asyncio
async def test_job_rehome_swaps_nonterminal_only(tmp_path):
    store = JobQueueStore(tmp_path)
    await store.initialize()
    pending = JobRecord(
        id="j1",
        dedupe_key="j1",
        folder_path="/old/root/pkg",
        status=JobStatus.PENDING,
        injector_script="/old/root/inject.py",
    )
    done = JobRecord(
        id="j2",
        dedupe_key="j2",
        folder_path="/old/root/other",
        status=JobStatus.DONE,
    )
    await store.append_job(pending)
    await store.append_job(done)

    n = await store.rehome(lambda p: prefix_swap(p, "/old/root", "/new/home"))
    assert n == 1

    reloaded = JobQueueStore(tmp_path)
    await reloaded.initialize()  # loads snapshot+JSONL into _jobs; returns stale
    # include_noop=True: `done` above is a no-op-shaped DONE record (no chunk
    # delta) and would otherwise be filtered by Fix 4's default listing
    # filter — irrelevant to what this test actually verifies (rehome leaves
    # a terminal job's folder_path untouched).
    jobs = {j.id: j for j in await reloaded.get_all_jobs(include_noop=True)}
    assert jobs["j1"].folder_path == "/new/home/pkg"
    assert jobs["j1"].injector_script == "/new/home/inject.py"
    assert jobs["j2"].folder_path == "/old/root/other"  # terminal untouched
