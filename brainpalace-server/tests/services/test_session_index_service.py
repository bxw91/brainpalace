"""Phase 050 — SessionIndexService: gate, dedup, subagent linking, resolver."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_index_service import (
    SessionIndexService,
    encode_project_to_sessions_dir,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"
PARENT = FIXTURES / "sess-parent-1.jsonl"


class FakeStore:
    """Minimal storage stand-in recording upserts; get_by_id models dedup."""

    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.upserts: list[list[str]] = []

    async def get_by_id(self, chunk_id: str):  # noqa: ANN201
        return {"id": chunk_id} if chunk_id in self.ids else None

    async def upsert_documents(
        self, ids, embeddings, documents, metadatas
    ):  # noqa: ANN001,ANN201
        self.upserts.append(list(ids))
        self.ids.update(ids)


class FakeEmbedder:
    def __init__(self) -> None:
        self.embedded = 0

    async def embed_chunks(self, chunks, progress=None):  # noqa: ANN001,ANN201
        self.embedded += len(chunks)
        return [[0.0, 0.1] for _ in chunks]


def _svc() -> tuple[SessionIndexService, FakeStore, FakeEmbedder]:
    store, emb = FakeStore(), FakeEmbedder()
    svc = SessionIndexService(embedding_generator=emb, storage_backend=store)
    return svc, store, emb


def test_encode_project_to_sessions_dir() -> None:
    d = encode_project_to_sessions_dir("/home/x/proj", home=Path("/home/x"))
    # Claude Code encodes cwd by replacing "/" with "-".
    assert d == Path("/home/x/.claude/projects/-home-x-proj")


@pytest.mark.asyncio
async def test_index_session_file_embeds_and_upserts() -> None:
    svc, store, emb = _svc()
    summary = await svc.index_session_file(PARENT)
    assert summary["session_id"] == "sess-parent-1"
    assert summary["chunks_new"] > 0
    assert emb.embedded == summary["chunks_new"]
    assert store.upserts  # something stored


@pytest.mark.asyncio
async def test_reingest_is_deduped_noop() -> None:
    svc, store, emb = _svc()
    await svc.index_session_file(PARENT)
    first_embedded = emb.embedded
    # Second pass: every chunk_id already present → nothing re-embedded.
    summary2 = await svc.index_session_file(PARENT)
    assert summary2["chunks_new"] == 0
    assert summary2["skipped"] > 0
    assert emb.embedded == first_embedded  # no new embeds


@pytest.mark.asyncio
async def test_disabled_config_indexes_nothing(tmp_path: Path) -> None:
    svc, store, emb = _svc()
    cfg = SessionIndexingConfig(enabled=False)
    summary = await svc.index_project("/work/proj", cfg, home=tmp_path)
    assert summary["enabled"] is False
    assert summary["files"] == 0
    assert emb.embedded == 0


@pytest.mark.asyncio
async def test_subagent_files_linked_to_parent(tmp_path: Path) -> None:
    svc, store, emb = _svc()
    cfg = SessionIndexingConfig(enabled=True, retain_days=100000)
    # Point the resolver at the fixtures dir directly via sessions_dir override.
    cfg = cfg.model_copy(update={"sessions_dir": str(FIXTURES)})
    summary = await svc.index_project("/work/proj", cfg, home=tmp_path)
    assert summary["enabled"] is True
    assert summary["files"] >= 2  # parent + subagent
    # parent linkage recorded for the subagent session
    assert "sess-sub-aaa" in summary["sessions"]
    assert summary["sessions"]["sess-sub-aaa"]["parent_session_id"] == "sess-parent-1"


@pytest.mark.asyncio
async def test_retain_days_skips_old_files(tmp_path: Path) -> None:
    svc, store, emb = _svc()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    old = sessions / "old.jsonl"
    old.write_text(PARENT.read_text())
    # Backdate mtime by 200 days.
    old_ts = time.time() - 200 * 86400
    import os

    os.utime(old, (old_ts, old_ts))
    cfg = SessionIndexingConfig(
        enabled=True, retain_days=90, sessions_dir=str(sessions)
    )
    summary = await svc.index_project("/work/proj", cfg, home=tmp_path)
    assert summary["files_skipped_old"] >= 1
