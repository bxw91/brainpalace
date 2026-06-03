"""Task 8 — THE GUARANTEE: no input leaves a session permanently un-marked.

For every injected failure (provider down, malformed-twice, oversized) the
session ends **un-marked** after the first pass, and a subsequent healthy
**catch-up** distils it → marked. The only permanent non-summarize paths are
``mode != provider`` and the kill switch (both applied by the caller, not here).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from brainpalace_server.services.session_distill_service import (
    SessionDistiller,
    is_marked,
)

_VALID = json.dumps({"summary": "recovered", "tools_used": ["Edit"]})


class FakeEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0, 1.0] for _ in chunks]


class FakeStorage:
    is_initialized = True

    def __init__(self):
        self.docs: dict[str, str] = {}

    async def delete_by_metadata(self, where):
        return None

    async def get_by_id(self, chunk_id):
        return None

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        for cid, doc in zip(ids, documents):
            self.docs[cid] = doc


class ErrorSummarizer:
    async def generate(self, prompt: str) -> str:
        raise RuntimeError("provider down")


class BadJSONSummarizer:
    async def generate(self, prompt: str) -> str:
        return "this is not json"


class GoodSummarizer:
    async def generate(self, prompt: str) -> str:
        return _VALID


def _write_transcript(path: Path, sid: str, *, turns: int = 2) -> Path:
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "sessionId": sid,
                "timestamp": "2026-06-03T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"work line {i}"}],
                },
            }
        )
        for i in range(turns)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _deps(project_root: Path):
    return {
        "embedder": FakeEmbedder(),
        "storage_backend": FakeStorage(),
        "project_root": str(project_root),
        "digest_path": str(project_root / "BRAINPALACE_DECISIONS.md"),
    }


def _make_quiescent(path: Path) -> None:
    old = os.path.getmtime(path) - 1000
    os.utime(path, (old, old))


@pytest.mark.parametrize(
    "broken,chunk_chars,turns",
    [
        (ErrorSummarizer, 48000, 2),  # provider outage
        (BadJSONSummarizer, 48000, 2),  # malformed output (twice)
        (ErrorSummarizer, 60, 40),  # oversized + a failing part
    ],
)
@pytest.mark.asyncio
async def test_failure_then_catchup_always_recovers(
    tmp_path, broken, chunk_chars, turns
):
    sid = "guard"
    t = _write_transcript(tmp_path / f"{sid}.jsonl", sid, turns=turns)
    _make_quiescent(t)

    # First pass with the broken summarizer: must end UN-marked (not dropped).
    bad = SessionDistiller(
        summarizer=broken(), chunk_chars=chunk_chars, **_deps(tmp_path)
    )
    assert await bad.maybe_distill(t) is None
    assert not is_marked(tmp_path, sid), "a failure must never mark a session"

    # Catch-up with a healthy summarizer: the same session is recovered + marked.
    good = SessionDistiller(
        summarizer=GoodSummarizer(), chunk_chars=chunk_chars, **_deps(tmp_path)
    )
    assert await good.catch_up([t]) == 1
    assert is_marked(tmp_path, sid), "catch-up must eventually mark every session"
