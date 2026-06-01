import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_archive_watcher import SessionArchiveWatcher


def _write(path: Path, sid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sessionId": sid,
                "timestamp": "2026-06-01T10:00:00Z",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_purge_deleted_removes_chunks(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write(live, "s1")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive_path = archive.sync(live)
    storage = AsyncMock()
    storage.delete_by_metadata.return_value = 3

    watcher = SessionArchiveWatcher(tmp_path / "arch", archive, storage)
    archive_path.unlink()  # curated away
    purged = await watcher.purge_deleted()

    assert purged == ["s1"]
    # ChromaDB requires $and to combine multiple metadata conditions.
    storage.delete_by_metadata.assert_awaited_once_with(
        {
            "$and": [
                {"source_type": "session_turn"},
                {"session_id": "s1"},
            ]
        }
    )
    assert archive.is_tombstoned("s1") is True


@pytest.mark.asyncio
async def test_purge_continues_when_one_delete_fails(tmp_path: Path) -> None:
    """A delete_by_metadata failure for one session must not abort the rest."""
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    paths = []
    for sid in ("s1", "s2", "s3"):
        live = tmp_path / "live" / f"{sid}.jsonl"
        _write(live, sid)
        archive.sync(live)
        paths.append(archive.manifest_entry(sid)["archive_path"])
    # Curate all three away.
    for p in paths:
        Path(p).unlink()

    storage = AsyncMock()

    # Fail on the middle session; succeed on the others.
    def _side_effect(where):
        sid = where["$and"][1]["session_id"]
        if sid == "s2":
            raise RuntimeError("boom")
        return 1

    storage.delete_by_metadata = AsyncMock(side_effect=_side_effect)

    watcher = SessionArchiveWatcher(tmp_path / "arch", archive, storage)
    purged = await watcher.purge_deleted()

    # All three reconciled+tombstoned despite the s2 purge failure.
    assert sorted(purged) == ["s1", "s2", "s3"]
    assert storage.delete_by_metadata.await_count == 3
    for sid in ("s1", "s2", "s3"):
        assert archive.is_tombstoned(sid) is True


@pytest.mark.asyncio
async def test_purge_empty_when_nothing_deleted(tmp_path: Path) -> None:
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    live = tmp_path / "live" / "keep.jsonl"
    _write(live, "keep")
    archive.sync(live)  # archive file still present
    storage = AsyncMock()

    watcher = SessionArchiveWatcher(tmp_path / "arch", archive, storage)
    purged = await watcher.purge_deleted()

    assert purged == []
    storage.delete_by_metadata.assert_not_awaited()
