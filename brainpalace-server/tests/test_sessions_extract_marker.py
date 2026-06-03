"""Task 7 — /sessions/extract writes the unified .done marker.

Any stored extraction (subagent submit OR provider distil) marks the session
done, so `auto`-engine flips never re-summarize an already-extracted session.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from brainpalace_server.api.routers.sessions import extract_session
from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_distill_service import is_marked


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


@pytest.mark.asyncio
async def test_extract_writes_done_marker(tmp_path, monkeypatch):
    storage = FakeStorage()
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                storage_backend=storage,
                project_root=str(tmp_path),
                memory_service=None,
            )
        )
    )
    monkeypatch.setattr(
        "brainpalace_server.indexing.get_embedding_generator",
        lambda: FakeEmbedder(),
    )
    payload = SessionExtraction(session_id="abc", summary="did x")

    await extract_session(payload, req)

    assert is_marked(tmp_path, "abc")
