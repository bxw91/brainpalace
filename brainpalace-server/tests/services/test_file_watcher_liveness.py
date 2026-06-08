import asyncio

import pytest

from brainpalace_server.services.file_watcher_service import FileWatcherService


@pytest.mark.asyncio
async def test_dead_task_count_detects_finished_tasks():
    svc = FileWatcherService.__new__(FileWatcherService)
    svc._tasks = {}

    async def runs_forever():
        await asyncio.sleep(3600)

    async def already_done():
        return None

    live = asyncio.create_task(runs_forever())
    done = asyncio.create_task(already_done())
    await asyncio.sleep(0)  # let `done` finish
    svc._tasks = {"/a": live, "/b": done}

    assert svc.dead_task_count() == 1
    live.cancel()
