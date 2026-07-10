from __future__ import annotations

import pytest

from brainpalace_server.models.memory import Memory
from brainpalace_server.services.memory_service import MemoryService
from brainpalace_server.services.session_context_service import SessionContextService


def test_memory_sensitivity_defaults_normal():
    m = Memory(id="m1", text="fact")
    assert m.sensitivity == "normal"


@pytest.mark.asyncio
async def test_sensitivity_roundtrips_through_markdown(tmp_path):
    svc = MemoryService(tmp_path / "MEM.md")
    await svc.add("public fact")
    await svc.add("secret fact", sensitivity="private")
    reloaded = {m.text: m.sensitivity for m in svc.load()}
    assert reloaded == {"public fact": "normal", "secret fact": "private"}


class _FakeHit:
    def __init__(self, cid, text, score, sensitivity):
        self.chunk_id = cid
        self.text = text
        self.score = score
        self.metadata = {
            "memory_id": cid,
            "section": "Notes",
            "tags": "",
            "sensitivity": sensitivity,
        }


class _FakeEmbeddings:
    async def embed_query(self, query):
        return [0.0]


class _FakeVectorStore:
    def __init__(self, hits):
        self._hits = hits

    async def similarity_search(self, query_embedding, top_k, similarity_threshold):
        return self._hits


@pytest.mark.asyncio
async def test_recall_default_deny_drops_private(tmp_path):
    hits = [
        _FakeHit("m1", "public", 0.9, "normal"),
        _FakeHit("m2", "secret", 0.9, "private"),
    ]
    svc = MemoryService(
        tmp_path / "MEM.md",
        vector_store=_FakeVectorStore(hits),
        embedding_generator=_FakeEmbeddings(),
    )
    denied, _ = await svc.recall("x", include_sensitive=False)
    assert {h.text for h in denied} == {"public"}
    revealed, _ = await svc.recall("x", include_sensitive=True)
    assert {h.text for h in revealed} == {"public", "secret"}


class _FakeMemoryStore:
    def __init__(self, memories):
        self._memories = memories

    def load(self):
        return self._memories


def test_build_push_surface_excludes_private_memory():
    normal = Memory(id="m1", text="public fact", origin="user")
    private = Memory(id="m2", text="secret fact", origin="user", sensitivity="private")
    svc = SessionContextService(memory_service=_FakeMemoryStore([normal, private]))
    ctx = svc.build(project_root="/proj")
    assert "public fact" in ctx.text
    assert "secret fact" not in ctx.text
    assert ctx.memory_count == 1
