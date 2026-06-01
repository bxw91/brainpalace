"""Unit tests for MemoryService markdown source-of-truth (Phase 030).

No Chroma / no embeddings here — vector_store is None, so these exercise the
markdown parse/write/dedup/cap logic only (keyless, in the normal suite)."""

from __future__ import annotations

import pytest

from brainpalace_server.services.memory_service import (
    MemoryCapError,
    MemoryDuplicateError,
    MemoryNotFoundError,
    MemoryService,
)


@pytest.fixture
def svc(tmp_path):
    return MemoryService(path=tmp_path / "BRAINPALACE_MEMORY.md")


async def test_add_and_load_roundtrip(svc):
    m = await svc.add(
        "staging url is staging.example.com",
        section="Environment",
        tags=["infra", "url"],
    )
    loaded = svc.load()
    assert len(loaded) == 1
    got = loaded[0]
    assert got.id == m.id
    assert got.text == "staging url is staging.example.com"
    assert got.section == "Environment"
    assert got.tags == ["infra", "url"]
    assert got.origin == "user"
    assert got.is_active


async def test_multiple_sections_grouped(svc):
    await svc.add("fact A", section="Environment")
    await svc.add("decision B", section="Decisions")
    text = svc.path.read_text()
    assert "## Environment" in text and "## Decisions" in text
    assert len(svc.load()) == 2


async def test_dedup_blocks_near_duplicate(svc):
    await svc.add("use Redis for the cache backend")
    with pytest.raises(MemoryDuplicateError):
        await svc.add("use Redis for the cache backend")
    # substring is also treated as duplicate
    with pytest.raises(MemoryDuplicateError):
        await svc.add("USE redis FOR the Cache Backend")


async def test_cap_refuses_oversize(tmp_path):
    svc = MemoryService(path=tmp_path / "m.md", char_cap=400)
    await svc.add("first fact that fits under the small cap")
    with pytest.raises(MemoryCapError):
        await svc.add("x" * 500)


async def test_obsolete_marks_inactive(svc):
    m = await svc.add("temporary fact")
    await svc.obsolete(m.id)
    loaded = svc.load()
    assert len(loaded) == 1
    assert not loaded[0].is_active
    assert loaded[0].obsoleted_at is not None


async def test_obsolete_frees_cap_room(svc):
    m = await svc.add("a fact")
    # an obsolete entry no longer counts as an active duplicate
    await svc.obsolete(m.id)
    again = await svc.add("a fact")
    assert again.id != m.id


async def test_delete_removes_entry(svc):
    m = await svc.add("ephemeral")
    await svc.delete(m.id)
    assert svc.load() == []


async def test_delete_missing_raises(svc):
    with pytest.raises(MemoryNotFoundError):
        await svc.delete("mem_doesnotexist")


async def test_hand_edited_unknown_lines_preserved(svc):
    await svc.add("real fact", section="Notes")
    # simulate a hand edit: prose line with no ab tag
    text = svc.path.read_text() + "\nsome human note without a tag\n"
    svc.path.write_text(text)
    # load ignores the untagged line but doesn't crash
    loaded = svc.load()
    assert len(loaded) == 1
    # the untagged line is still on disk
    assert "some human note without a tag" in svc.path.read_text()


async def test_rebuild_without_index_is_noop(svc):
    await svc.add("fact")
    assert await svc.rebuild_from_markdown() == 0  # no vector store wired


async def test_recall_without_index_empty(svc):
    await svc.add("fact")
    hits, ms = await svc.recall("fact")
    assert hits == [] and ms == 0.0
