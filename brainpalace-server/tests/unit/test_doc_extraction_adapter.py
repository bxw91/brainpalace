import pytest

from brainpalace_server.services.doc_extraction_adapter import DocExtractionAdapter
from brainpalace_server.storage.extraction_pending import DocPendingStore


class _FakeProvider:
    def __init__(self, reply="A | uses | B", boom=False):
        self._reply, self._boom = reply, boom

    async def generate(self, prompt):
        if self._boom:
            raise RuntimeError("down")
        return self._reply


class _FakeGraph:
    def __init__(self):
        self.added = []
        self.persisted = 0

    def add_triplet(self, **kw):
        self.added.append(kw)
        return True

    def persist(self):
        self.persisted += 1


@pytest.mark.asyncio
async def test_process_defers_persist_and_mark_to_flush(tmp_path):
    # 2-6: process adds triplets in-memory + queues the done chunk; the graph is
    # persisted (and chunks marked done) once per batch in flush().
    store = DocPendingStore(tmp_path / "p.db")
    store.mark_pending("c1", "alpha beta")
    graph = _FakeGraph()
    ad = DocExtractionAdapter(
        store=store, graph_store=graph, provider_factory=lambda: _FakeProvider()
    )
    items = await ad.select_pending(10)
    assert items == [("c1", "alpha beta")]
    assert await ad.process(items[0]) is True
    assert graph.added  # triplets added in-memory
    assert graph.persisted == 0  # not persisted yet — deferred (2-6)
    assert store.count_pending() == 1  # not marked done until flush (crash-safe)
    await ad.flush()
    assert graph.persisted == 1  # persisted exactly once for the batch
    assert store.count_pending() == 0  # now marked done


@pytest.mark.asyncio
async def test_flush_persists_once_for_a_multi_chunk_batch(tmp_path):
    store = DocPendingStore(tmp_path / "p.db")
    store.mark_pending("c1", "alpha")
    store.mark_pending("c2", "beta")
    graph = _FakeGraph()
    ad = DocExtractionAdapter(
        store=store, graph_store=graph, provider_factory=lambda: _FakeProvider()
    )
    for it in await ad.select_pending(10):
        assert await ad.process(it) is True
    assert graph.persisted == 0
    await ad.flush()
    assert graph.persisted == 1  # one persist for the whole batch, not per chunk
    assert store.count_pending() == 0


@pytest.mark.asyncio
async def test_flush_noop_when_nothing_processed(tmp_path):
    store = DocPendingStore(tmp_path / "p.db")
    ad = DocExtractionAdapter(
        store=store, graph_store=_FakeGraph(), provider_factory=lambda: _FakeProvider()
    )
    await ad.flush()  # nothing dirty → no persist, no error


@pytest.mark.asyncio
async def test_provider_failure_leaves_pending(tmp_path):
    store = DocPendingStore(tmp_path / "p.db")
    store.mark_pending("c1", "alpha")
    ad = DocExtractionAdapter(
        store=store,
        graph_store=_FakeGraph(),
        provider_factory=lambda: _FakeProvider(boom=True),
    )
    assert await ad.process(("c1", "alpha")) is False
    assert store.count_pending() == 1  # still pending → retried
