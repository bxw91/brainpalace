"""Read-only self-heal: recovery still runs (cache-only) but stage-2 is skipped."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from brainpalace_server.services import startup_reconcile


@pytest.mark.asyncio
async def test_read_only_skips_stage2(monkeypatch):
    drop = AsyncMock()
    deep = AsyncMock()
    monkeypatch.setattr(startup_reconcile, "reconcile_store_against_manifest", drop)
    monkeypatch.setattr(startup_reconcile, "deep_clean", deep)

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()
    vector_store = MagicMock(persist_dir="/tmp")

    report = await startup_reconcile.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=vector_store,
        cache_db_path=None,
        target_dimensions=0,
        read_only=True,
    )

    drop.assert_not_called()
    deep.assert_not_called()
    assert report["deep_clean_ran"] is False
    assert report["deep_clean_skipped_reason"] == "read-only mode"
