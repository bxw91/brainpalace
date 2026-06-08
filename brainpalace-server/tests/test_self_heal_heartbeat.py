from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import brainpalace_server.self_heal as sh


@pytest.mark.asyncio
async def test_heal_once_restarts_dead_watcher_and_worker(monkeypatch):
    # watcher: 1 dead task, 1 auto folder expected -> heal (stop+start)
    watcher = MagicMock()
    watcher.dead_task_count.return_value = 1
    watcher.expected_auto_folder_count = AsyncMock(return_value=1)
    watcher.watched_folder_count = 1
    watcher.stop = AsyncMock()
    watcher.start = AsyncMock()

    # worker: not running -> restart
    worker = MagicMock()
    worker.is_running.return_value = False
    worker.start = AsyncMock()

    vector = MagicMock()
    vector.heal_if_corrupt = AsyncMock(return_value=0)

    app = SimpleNamespace(
        state=SimpleNamespace(
            file_watcher_service=watcher,
            job_worker=worker,
            vector_store=vector,
            state_dir=None,
            project_root="",
        )
    )

    healer = sh.HealState()
    await sh.heal_once(app, healer)

    watcher.stop.assert_awaited_once()
    watcher.start.assert_awaited_once()
    worker.start.assert_awaited_once()
    vector.heal_if_corrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_restart_capped(monkeypatch):
    worker = MagicMock()
    worker.is_running.return_value = False
    worker.start = AsyncMock()
    app = SimpleNamespace(
        state=SimpleNamespace(
            file_watcher_service=None,
            job_worker=worker,
            vector_store=None,
            state_dir=None,
            project_root="",
        )
    )
    healer = sh.HealState()
    for _ in range(sh.MAX_WORKER_RESTARTS + 3):
        await sh.heal_once(app, healer)
    assert worker.start.await_count == sh.MAX_WORKER_RESTARTS
