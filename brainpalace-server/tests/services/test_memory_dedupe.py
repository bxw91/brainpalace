import pytest

from brainpalace_server.services.memory_service import MemoryService


class _FakeEmb:
    async def embed_query(self, text):
        return [0.0]

    async def embed_text(self, text):
        return [0.0]


class _FakeVS:
    """Returns a scripted top hit for similarity_search."""

    def __init__(self):
        self.hit = None

    async def similarity_search(self, query_embedding, top_k, similarity_threshold):
        return [self.hit] if self.hit is not None else []

    async def upsert_documents(self, **kwargs):
        return None

    async def delete_by_ids(self, ids):
        return None


class _Hit:
    def __init__(self, memory_id, score):
        self.chunk_id = memory_id
        self.score = score
        self.text = ""
        self.metadata = {"memory_id": memory_id}


@pytest.mark.asyncio
async def test_no_dedupe_without_embeddings(tmp_path):
    # Vector store / embeddings absent → dedupe is a no-op (today's behavior).
    svc = MemoryService(path=tmp_path / "m.md")
    a = await svc.add("staging url is s1.example.com", origin="user")
    # A semantically-near but not exact/substring fact: both coexist (no embeddings).
    b = await svc.add("the staging endpoint lives at s2.example.com", origin="user")
    ids = {m.id for m in svc.load() if m.is_active}
    assert a.id in ids and b.id in ids


@pytest.mark.asyncio
async def test_write_time_supersede_on_strong_match(tmp_path):
    vs = _FakeVS()
    svc = MemoryService(
        path=tmp_path / "m.md", vector_store=vs, embedding_generator=_FakeEmb()
    )
    first = await svc.add("staging url is s1.example.com", origin="user")
    # Script a strong match to `first` for the next add.
    vs.hit = _Hit(first.id, score=0.99)
    second = await svc.add("staging endpoint is s2.example.com", origin="user")
    active = [m for m in svc.load() if m.is_active]
    ids = {m.id for m in active}
    assert second.id in ids
    assert first.id not in ids  # superseded (physically removed — newest wins)
    assert len(active) == 1


@pytest.mark.asyncio
async def test_weak_match_below_threshold_keeps_both(tmp_path):
    vs = _FakeVS()
    svc = MemoryService(
        path=tmp_path / "m.md", vector_store=vs, embedding_generator=_FakeEmb()
    )
    first = await svc.add("staging url is s1.example.com", origin="user")
    vs.hit = _Hit(first.id, score=0.50)  # below 0.92 default
    second = await svc.add("prod url is p1.example.com", origin="user")
    ids = {m.id for m in svc.load() if m.is_active}
    assert first.id in ids and second.id in ids
