"""End-to-end integration test for the session archive pipeline.

Verifies that:
- SessionWatcher (with archive=) ingests via the archive copy
- Deleting the archive copy and calling purge_deleted removes chunks
- Re-ingesting after purge is a no-op (tombstone prevents re-archive)
"""

import json
from pathlib import Path

import pytest

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_archive_watcher import SessionArchiveWatcher
from brainpalace_server.services.session_index_service import SessionIndexService
from brainpalace_server.services.session_watcher import SessionWatcher


class _FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def get_by_id(self, cid: str):
        return self.docs.get(cid)

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        for cid, md in zip(ids, metadatas):
            self.docs[cid] = md

    async def delete_by_metadata(self, where: dict) -> int:
        # Mirror ChromaDB's $and semantics: every condition must match.
        conditions = where["$and"]
        gone = [
            c
            for c, md in self.docs.items()
            if all(md.get(k) == v for cond in conditions for k, v in cond.items())
        ]
        for c in gone:
            del self.docs[c]
        return len(gone)


class _FakeEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0] for _ in chunks]


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
async def test_archive_index_then_delete_purges(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write(live, "s1")
    store = _FakeStore()
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    index = SessionIndexService(_FakeEmbedder(), store)
    watcher = SessionWatcher(
        tmp_path / "live", index, SessionIndexingConfig(enabled=True), archive=archive
    )

    await watcher._ingest_paths({str(live)})
    assert store.docs, "expected indexed chunks from the archive copy"
    assert all(
        md["source_path"].startswith(str(tmp_path / "arch"))
        for md in store.docs.values()
    )

    archive_path = Path(archive.manifest_entry("s1")["archive_path"])
    archive_path.unlink()
    del_watcher = SessionArchiveWatcher(tmp_path / "arch", archive, store)
    purged = await del_watcher.purge_deleted()
    assert purged == ["s1"]
    assert store.docs == {}
    await watcher._ingest_paths({str(live)})
    assert store.docs == {}
