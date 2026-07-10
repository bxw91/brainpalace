import pytest

from brainpalace_server.models.memory import Memory
from brainpalace_server.services.memory_service import MemoryCapError, MemoryService


def _mem(id, origin, conf=1.0, last_ref=None, created="2026-01-01T00:00:00+00:00"):
    return Memory(
        id=id,
        text=f"t {id}",
        origin=origin,
        confidence=conf,
        last_referenced_at=last_ref,
        created_at=created,
    )


def test_only_session_origin_is_evictable(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md")
    assert svc._is_evictable(_mem("a", "session:s1")) is True
    assert svc._is_evictable(_mem("b", "user")) is False
    assert svc._is_evictable(_mem("c", "ai")) is False
    obsolete = _mem("d", "session:s1")
    obsolete.obsoleted_at = "2026-01-02T00:00:00+00:00"
    assert svc._is_evictable(obsolete) is False  # already inactive


def test_eviction_order_oldest_lowest_conf_first(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md")
    mems = [
        _mem("keep_user", "user"),
        _mem("new", "session:s", last_ref="2026-06-01T00:00:00+00:00"),
        _mem("old", "session:s", last_ref="2026-01-01T00:00:00+00:00"),
        _mem(
            "old_lowconf", "session:s", conf=0.2, last_ref="2026-01-01T00:00:00+00:00"
        ),
    ]
    order = [m.id for m in svc._eviction_order(mems)]
    assert "keep_user" not in order
    assert order[0] == "old_lowconf"  # same date, lower conf first
    assert order.index("old") < order.index("new")


@pytest.mark.asyncio
async def test_reclaim_deletes_oldest_session_fact_to_admit_new(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md", char_cap=500)
    # Fill with two session facts; small cap so a third would overflow.
    await svc.add("alpha fact one padding padding padding", origin="session:s1")
    await svc.add("beta fact two padding padding padding", origin="session:s2")
    assert svc.char_count() <= svc.char_cap
    # Reclaim path admits the new fact by DELETING the oldest session entry
    # (obsoleting would not shrink the file — Hardening decision 1).
    await svc.add(
        "gamma newest padding padding padding", origin="session:s3", reclaim=True
    )
    all_texts = [m.text for m in svc.load()]  # ALL entries, not just active
    assert any("gamma" in t for t in all_texts)
    assert not any("alpha" in t for t in all_texts)  # physically removed
    assert svc.char_count() <= svc.char_cap


@pytest.mark.asyncio
async def test_reclaim_protects_user_facts_then_raises(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md", char_cap=300)
    await svc.add("manual sacred fact padding padding", origin="user")
    with pytest.raises(MemoryCapError):
        await svc.add(
            "promoted overflow padding padding padding padding",
            origin="session:s1",
            reclaim=True,
        )
    # The manual fact survived.
    assert any(m.origin == "user" for m in svc.load())


@pytest.mark.asyncio
async def test_reclaim_obsoletes_cross_session_superseded_entry(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md", char_cap=8000)
    await svc.add(
        "use Postgres — chosen for JSONB",
        origin="session:s1",
        tags=["session-decision"],
    )
    await svc.add(
        "use SQLite — simpler local dev",
        origin="session:s2",
        tags=["session-decision"],
        reclaim=True,
        supersedes="use Postgres",
    )
    all_texts = [m.text for m in svc.load()]  # ALL entries
    assert not any("Postgres" in t for t in all_texts)  # deleted, not just obsoleted
    assert any("SQLite" in t for t in all_texts)
