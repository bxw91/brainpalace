"""Task 6 — `auto` mode distill-time reconciliation + 24h safety net.

In ``auto`` mode the server distiller defers to the plugin's subagent when the
plugin is installed — UNLESS the session is un-marked AND older than the grace
window (a disabled/never-reopened plugin safety net). ``provider`` mode ignores
the plugin entirely.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from brainpalace_server.services.session_distill_service import (
    SessionDistiller,
    is_marked,
)

# --------------------------------------------------------------------------- #
# Fakes (copied from test_session_distill_service.py)
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
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


_VALID = json.dumps({"summary": "ok", "tools_used": ["Edit"]})


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


def _make_quiescent(path: Path, *, age_seconds: float = 3600.0) -> Path:
    """Backdate mtime so the transcript reads as quiescent (idle), yet still
    young enough (1h) to be 'fresh' against the 24h grace window."""
    old = time.time() - age_seconds
    os.utime(path, (old, old))
    return path


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_auto_defers_when_plugin_present_and_fresh(tmp_path):
    t = _write_transcript(tmp_path / "s.jsonl", "s")
    _make_quiescent(t)
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(
        summarizer=summ, mode="auto", plugin_present=lambda: True, **_deps(tmp_path)
    )
    assert await d.maybe_distill(t) is None  # deferred to subagent
    assert summ.calls == 0
    assert not is_marked(tmp_path, "s")


@pytest.mark.asyncio
async def test_auto_safety_net_when_plugin_present_but_stale(tmp_path):
    t = _write_transcript(tmp_path / "s.jsonl", "s")
    old = time.time() - 48 * 3600
    os.utime(t, (old, old))
    summ = CannedSummarizer(_VALID)
    d = SessionDistiller(
        summarizer=summ,
        mode="auto",
        plugin_present=lambda: True,
        grace_hours=24,
        **_deps(tmp_path),
    )
    assert await d.maybe_distill(t) is not None  # safety net fired
    assert is_marked(tmp_path, "s")


@pytest.mark.asyncio
async def test_auto_distils_when_no_plugin(tmp_path):
    t = _write_transcript(tmp_path / "s.jsonl", "s")
    _make_quiescent(t)
    d = SessionDistiller(
        summarizer=CannedSummarizer(_VALID),
        mode="auto",
        plugin_present=lambda: False,
        **_deps(tmp_path),
    )
    assert await d.maybe_distill(t) is not None
    assert is_marked(tmp_path, "s")


@pytest.mark.asyncio
async def test_provider_mode_ignores_plugin(tmp_path):
    t = _write_transcript(tmp_path / "s.jsonl", "s")
    _make_quiescent(t)
    d = SessionDistiller(
        summarizer=CannedSummarizer(_VALID),
        mode="provider",
        plugin_present=lambda: True,
        **_deps(tmp_path),
    )
    assert await d.maybe_distill(t) is not None
