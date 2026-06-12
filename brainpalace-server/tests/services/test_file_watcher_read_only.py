"""Read-only: the file watcher must not enqueue reindex jobs."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_watcher_skips_enqueue_when_read_only(monkeypatch):
    from brainpalace_server.services import file_watcher_service as fw

    monkeypatch.setattr(fw, "is_read_only", lambda: True)

    folder_manager = MagicMock()
    job_service = MagicMock()
    job_service.enqueue_job = AsyncMock()
    service = fw.FileWatcherService(folder_manager, job_service)

    await service._enqueue_for_folder("/tmp/x")

    job_service.enqueue_job.assert_not_called()
