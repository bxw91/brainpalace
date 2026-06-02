"""Phase 050 — SessionWatcher ingest-handler + lifecycle (no real fs events)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_watcher import SessionWatcher

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"
PARENT = FIXTURES / "sess-parent-1.jsonl"


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def index_session_file(self, path, **kw):  # noqa: ANN001,ANN003,ANN201
        self.calls.append(str(path))


def _watcher(svc: RecordingService) -> SessionWatcher:
    return SessionWatcher(FIXTURES, svc, SessionIndexingConfig(enabled=True))


async def test_ingest_paths_filters_non_jsonl_and_missing() -> None:
    svc = RecordingService()
    w = _watcher(svc)
    n = await w._ingest_paths(
        {str(PARENT), str(FIXTURES / "note.txt"), str(FIXTURES / "ghost.jsonl")}
    )
    assert n == 1
    assert svc.calls == [str(PARENT)]  # only the existing .jsonl


async def test_start_noop_when_dir_missing(tmp_path: Path) -> None:
    svc = RecordingService()
    w = SessionWatcher(tmp_path / "nope", svc, SessionIndexingConfig(enabled=True))
    await w.start()
    assert w.is_running is False
    await w.stop()  # safe even when never started


async def test_start_stop_lifecycle() -> None:
    svc = RecordingService()
    w = _watcher(svc)
    await w.start()
    assert w.is_running is True
    await w.stop()
    assert w.is_running is False


# --- archive integration ---


def _write_transcript(path: Path, sid: str) -> None:
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


async def test_ingest_syncs_then_indexes_archive_path(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write_transcript(live, "s1")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    service = AsyncMock()
    cfg = SessionIndexingConfig(enabled=True)

    watcher = SessionWatcher(tmp_path / "live", service, cfg, archive=archive)
    await watcher._ingest_paths({str(live)})

    service.index_session_file.assert_awaited_once()
    called_path = service.index_session_file.call_args.args[0]
    assert str(called_path).startswith(str(tmp_path / "arch"))  # archive, not live
    assert service.index_session_file.call_args.kwargs["origin_path"] == str(live)


async def test_ingest_skips_tombstoned(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s2.jsonl"
    _write_transcript(live, "s2")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive.tombstone("s2", origin_path=str(live))
    service = AsyncMock()
    watcher = SessionWatcher(
        tmp_path / "live", service, SessionIndexingConfig(), archive=archive
    )
    await watcher._ingest_paths({str(live)})
    service.index_session_file.assert_not_awaited()


async def test_archive_only_does_not_index(tmp_path: Path) -> None:
    """index_enabled=False ⇒ archive.sync runs, index_session_file does not."""
    live = tmp_path / "live" / "s3.jsonl"
    _write_transcript(live, "s3")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    service = AsyncMock()
    watcher = SessionWatcher(
        tmp_path / "live",
        service,
        SessionIndexingConfig(enabled=False),
        archive=archive,
        index_enabled=False,
    )

    n = await watcher._ingest_paths({str(live)})

    assert n == 1  # archived
    service.index_session_file.assert_not_awaited()  # not indexed
    assert archive.manifest_entry("s3") is not None  # raw copy made
    assert (tmp_path / "arch" / "2026-06-01-claude-code" / "s3.jsonl").exists()


async def test_index_enabled_does_both(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s4.jsonl"
    _write_transcript(live, "s4")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    service = AsyncMock()
    watcher = SessionWatcher(
        tmp_path / "live",
        service,
        SessionIndexingConfig(enabled=True),
        archive=archive,
        index_enabled=True,
    )

    await watcher._ingest_paths({str(live)})

    service.index_session_file.assert_awaited_once()
    assert archive.manifest_entry("s4") is not None
