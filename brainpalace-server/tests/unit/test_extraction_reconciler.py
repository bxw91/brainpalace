import pytest

from brainpalace_server.services.extraction_reconciler import drain_once


class _FakeAdapter:
    def __init__(self, name, items, *, ready=True, fail=()):
        self.name = name
        self._items = list(items)
        self.is_ready = ready
        self._fail = set(fail)
        self.processed: list[str] = []

    async def select_pending(self, limit):
        return self._items[:limit]

    async def process(self, item):
        if item in self._fail:
            return False
        self.processed.append(item)
        self._items.remove(item)
        return True


@pytest.mark.asyncio
async def test_drain_respects_max_count_across_adapters():
    a = _FakeAdapter("doc", ["d1", "d2", "d3"])
    b = _FakeAdapter("session", ["s1", "s2"])
    res = await drain_once([a, b], max_count=3)
    assert res["processed"] == 3
    assert len(a.processed) + len(b.processed) == 3


@pytest.mark.asyncio
async def test_not_ready_adapter_skipped():
    a = _FakeAdapter("doc", ["d1"], ready=False)
    res = await drain_once([a], max_count=5)
    assert res == {"processed": 0, "failed": 0}
    assert a.processed == []


@pytest.mark.asyncio
async def test_failed_item_counted_not_marked():
    a = _FakeAdapter("doc", ["d1", "d2"], fail={"d1"})
    res = await drain_once([a], max_count=5)
    assert res["processed"] == 1 and res["failed"] == 1
    assert a.processed == ["d2"]
