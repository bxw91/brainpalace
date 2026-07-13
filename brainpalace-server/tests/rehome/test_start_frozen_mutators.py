# tests/rehome/test_start_frozen_mutators.py
"""Resume-endpoint fix: after an in-process resume completes, the background
mutators frozen under quarantine (job worker, file watcher, session reconciler)
are started so live indexing resumes without a server restart."""

from types import SimpleNamespace

import pytest

from brainpalace_server.rehome.quarantine import start_frozen_mutators


class _FakeWorker:
    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True


@pytest.mark.asyncio
async def test_starts_all_present_workers():
    jw, fw, sr = _FakeWorker(), _FakeWorker(), _FakeWorker()
    app_state = SimpleNamespace(
        job_worker=jw, file_watcher_service=fw, session_reconciler=sr
    )
    started = await start_frozen_mutators(app_state)
    assert set(started) == {"job_worker", "file_watcher_service", "session_reconciler"}
    assert jw.started and fw.started and sr.started


@pytest.mark.asyncio
async def test_skips_absent_and_survives_one_failure():
    class _Boom:
        async def start(self):
            raise RuntimeError("nope")

    jw = _FakeWorker()
    app_state = SimpleNamespace(
        job_worker=jw, file_watcher_service=_Boom(), session_reconciler=None
    )
    started = await start_frozen_mutators(app_state)
    assert started == ["job_worker"]  # boom skipped, None skipped, jw started
    assert jw.started
