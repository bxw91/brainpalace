"""Task 4 — server provider-distiller: guaranteed, no-silent-skip behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from brainpalace_server.services.session_distill_service import (
    SessionDistiller,
    distill_transcript,
    filter_transcript,
    is_marked,
    is_quiescent,
    marker_path,
)

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0, 1.0] for _ in chunks]


class FakeStorage:
    is_initialized = True

    def __init__(self):
        self.docs: dict[str, str] = {}

    async def delete_by_metadata(self, where):  # noqa: ANN001
        return None

    async def get_by_id(self, chunk_id):  # noqa: ANN001
        return None

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        for cid, doc in zip(ids, documents):
            self.docs[cid] = doc


class CannedSummarizer:
    """Returns the same reply every call; counts calls."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


class SequenceSummarizer:
    """Returns successive replies; repeats the last once exhausted."""

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        i = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        return self.replies[i]


class ErrorSummarizer:
    def __init__(self):
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("provider down")


_VALID = json.dumps({"summary": "did the thing", "tools_used": ["Edit"]})


def _write_transcript(path: Path, sid: str, *, turns: int = 2) -> Path:
    lines = []
    for i in range(turns):
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "sessionId": sid,
                    "cwd": "/proj",
                    "gitBranch": "main",
                    "timestamp": "2026-06-03T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"line {i} of work"}],
                    },
                }
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _deps(project_root: Path):
    return {
        "embedder": FakeEmbedder(),
        "storage_backend": FakeStorage(),
        "project_root": str(project_root),
        "digest_path": str(project_root / "BRAINPALACE_DECISIONS.md"),
    }


# --------------------------------------------------------------------------- #
# filter_transcript (shared contract)
# --------------------------------------------------------------------------- #


def test_filter_transcript_renders_turns(tmp_path):
    t = _write_transcript(tmp_path / "s.jsonl", "sid1")
    text = filter_transcript(t)
    assert "line 0 of work" in text
    assert "assistant" in text


# --------------------------------------------------------------------------- #
# distill_transcript core
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_valid_json_stored_and_marked(tmp_path):
    t = _write_transcript(tmp_path / "sidA.jsonl", "sidA")
    deps = _deps(tmp_path)
    result = await distill_transcript(t, summarizer=CannedSummarizer(_VALID), **deps)
    assert result is not None
    assert result.session_id == "sidA"
    assert deps["storage_backend"].docs  # stored
    assert is_marked(tmp_path, "sidA")


@pytest.mark.asyncio
async def test_malformed_twice_unmarked(tmp_path):
    t = _write_transcript(tmp_path / "sidB.jsonl", "sidB")
    summ = CannedSummarizer("not json at all")
    result = await distill_transcript(t, summarizer=summ, **_deps(tmp_path))
    assert result is None
    assert not is_marked(tmp_path, "sidB")
    assert summ.calls == 2  # primary + reminder retry


@pytest.mark.asyncio
async def test_malformed_then_valid_recovers(tmp_path):
    t = _write_transcript(tmp_path / "sidC.jsonl", "sidC")
    summ = SequenceSummarizer(["garbage", _VALID])
    result = await distill_transcript(t, summarizer=summ, **_deps(tmp_path))
    assert result is not None
    assert is_marked(tmp_path, "sidC")


@pytest.mark.asyncio
async def test_provider_error_unmarked(tmp_path):
    t = _write_transcript(tmp_path / "sidD.jsonl", "sidD")
    summ = ErrorSummarizer()
    result = await distill_transcript(t, summarizer=summ, **_deps(tmp_path))
    assert result is None
    assert not is_marked(tmp_path, "sidD")
    assert summ.calls == 2  # retried once


@pytest.mark.asyncio
async def test_oversized_chunked_and_merged(tmp_path):
    t = _write_transcript(tmp_path / "sidE.jsonl", "sidE", turns=40)
    summ = CannedSummarizer(_VALID)
    result = await distill_transcript(
        t, summarizer=summ, chunk_chars=80, **_deps(tmp_path)
    )
    assert result is not None
    assert is_marked(tmp_path, "sidE")
    assert summ.calls >= 3  # ≥2 parts + 1 merge


# --------------------------------------------------------------------------- #
# Quiescence + marker + SessionDistiller gating
# --------------------------------------------------------------------------- #


def test_is_quiescent_idle_and_newer(tmp_path):
    t = _write_transcript(tmp_path / "q.jsonl", "q")
    now = os.path.getmtime(t)
    assert is_quiescent(t, idle_seconds=300, now=now + 1000) is True
    assert is_quiescent(t, idle_seconds=300, now=now + 1) is False
    assert is_quiescent(t, idle_seconds=300, now=now + 1, newer_exists=True) is True


@pytest.mark.asyncio
async def test_active_transcript_deferred_not_dropped(tmp_path):
    t = _write_transcript(tmp_path / "sidF.jsonl", "sidF")  # mtime = now
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(summarizer=summ, **_deps(tmp_path))
    result = await d.maybe_distill(t)  # fresh → not quiescent
    assert result is None
    assert summ.calls == 0
    assert not is_marked(tmp_path, "sidF")


@pytest.mark.asyncio
async def test_quiescent_distilled_once(tmp_path):
    t = _write_transcript(tmp_path / "sidG.jsonl", "sidG")
    old = os.path.getmtime(t) - 1000
    os.utime(t, (old, old))
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(summarizer=summ, **_deps(tmp_path))
    assert await d.maybe_distill(t) is not None
    assert is_marked(tmp_path, "sidG")
    # second call is a no-op (already marked)
    assert await d.maybe_distill(t) is None
    assert summ.calls == 1


@pytest.mark.asyncio
async def test_already_marked_noop(tmp_path):
    t = _write_transcript(tmp_path / "sidH.jsonl", "sidH")
    mp = marker_path(tmp_path, "sidH")
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("done")
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(summarizer=summ, **_deps(tmp_path))
    assert await d.maybe_distill(t, newer_exists=True) is None
    assert summ.calls == 0


@pytest.mark.asyncio
async def test_catch_up_distills_old_unmarked(tmp_path):
    old_t = _write_transcript(tmp_path / "old.jsonl", "old")
    new_t = _write_transcript(tmp_path / "new.jsonl", "new")
    # old is older than new → old has a newer sibling → quiescent
    base = os.path.getmtime(new_t)
    os.utime(old_t, (base - 5000, base - 5000))
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(summarizer=summ, **_deps(tmp_path))
    count = await d.catch_up([old_t, new_t])
    assert count >= 1
    assert is_marked(tmp_path, "old")


@pytest.mark.asyncio
async def test_watcher_schedules_distill_on_archive(tmp_path):
    """SessionWatcher fires the distiller (when present) after archiving."""
    from brainpalace_server.config.session_config import SessionIndexingConfig
    from brainpalace_server.services.session_watcher import SessionWatcher

    t = _write_transcript(tmp_path / "w.jsonl", "w")

    class FakeArchive:
        def sync(self, p, *, tool=None):
            return Path(p)

    scheduled: list = []

    class SpyDistiller:
        def schedule(self, path, **kw):
            scheduled.append(path)

    watcher = SessionWatcher(
        tmp_path,
        None,
        SessionIndexingConfig(enabled=False),
        archive=FakeArchive(),
        index_enabled=False,
        distiller=SpyDistiller(),
    )
    await watcher._ingest_paths({str(t)})
    assert scheduled == [t]


@pytest.mark.asyncio
async def test_malformed_then_catchup_redistills(tmp_path):
    """Malformed → unmarked; a later catch-up with good output distils it."""
    t = _write_transcript(tmp_path / "sidI.jsonl", "sidI")
    old = os.path.getmtime(t) - 1000
    os.utime(t, (old, old))
    # First pass: bad output, stays unmarked.
    bad = SessionDistiller(summarizer=CannedSummarizer("nope"), **_deps(tmp_path))
    assert await bad.maybe_distill(t) is None
    assert not is_marked(tmp_path, "sidI")
    # Catch-up pass: good output → distilled + marked.
    good = SessionDistiller(summarizer=CannedSummarizer(_VALID), **_deps(tmp_path))
    assert await good.catch_up([t]) == 1
    assert is_marked(tmp_path, "sidI")
