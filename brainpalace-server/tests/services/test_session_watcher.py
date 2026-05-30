"""Phase 050 — SessionWatcher ingest-handler + lifecycle (no real fs events)."""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.config.session_config import SessionIndexingConfig
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
