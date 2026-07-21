"""A watcher over a global, cross-project store must archive only our project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_watcher import SessionWatcher


class _RecordingArchive:
    def __init__(self) -> None:
        self.synced: list[tuple[str, str | None]] = []

    def sync(self, path, *, tool=None):
        self.synced.append((str(path), tool))
        return Path(str(path) + ".archived")


class _OwnsOnlyOurProject:
    slug = "codex"

    def owns(self, path: Path, project_root: str) -> bool:
        obj = json.loads(Path(path).read_text(encoding="utf-8").splitlines()[0])
        return obj.get("cwd") == project_root


def _rollout(tmp_path: Path, name: str, cwd: str) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"cwd": cwd}) + "\n", encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_foreign_project_transcript_is_never_archived(tmp_path):
    ours = _rollout(tmp_path, "ours.jsonl", "/proj/ours")
    theirs = _rollout(tmp_path, "theirs.jsonl", "/proj/theirs")

    archive = _RecordingArchive()
    watcher = SessionWatcher(
        sessions_dir=tmp_path,
        service=None,
        config=SessionIndexingConfig(),
        archive=archive,
        index_enabled=False,
        adapter=_OwnsOnlyOurProject(),
        project_root="/proj/ours",
    )

    handled = await watcher._ingest_paths({str(ours), str(theirs)})

    assert handled == 1
    assert [p for p, _tool in archive.synced] == [str(ours)]


@pytest.mark.asyncio
async def test_slug_is_passed_to_sync(tmp_path):
    ours = _rollout(tmp_path, "ours.jsonl", "/proj/ours")
    archive = _RecordingArchive()
    watcher = SessionWatcher(
        sessions_dir=tmp_path,
        service=None,
        config=SessionIndexingConfig(),
        archive=archive,
        index_enabled=False,
        adapter=_OwnsOnlyOurProject(),
        project_root="/proj/ours",
    )

    await watcher._ingest_paths({str(ours)})

    assert archive.synced == [(str(ours), "codex")]


@pytest.mark.asyncio
async def test_no_adapter_means_no_filtering(tmp_path):
    """Back-compat: the pre-adapter constructor archives everything."""
    ours = _rollout(tmp_path, "ours.jsonl", "/proj/ours")
    archive = _RecordingArchive()
    watcher = SessionWatcher(
        sessions_dir=tmp_path,
        service=None,
        config=SessionIndexingConfig(),
        archive=archive,
        index_enabled=False,
    )

    handled = await watcher._ingest_paths({str(ours)})

    assert handled == 1
    assert archive.synced == [(str(ours), None)]
