"""Unit tests for SessionContextService (Phase 035). Keyless — memory_service
has vector_store=None, so no embeddings are touched."""

from __future__ import annotations

import pytest

from brainpalace_server.services.memory_service import MemoryService
from brainpalace_server.services.session_context_service import SessionContextService


@pytest.fixture
def mem(tmp_path):
    return MemoryService(path=tmp_path / "BRAINPALACE_MEMORY.md")


def test_project_facts_always_present(mem):
    svc = SessionContextService(memory_service=mem)
    ctx = svc.build(project_root="/p", branch="main", doc_count=42)
    assert "project_facts" in ctx.sections
    assert "/p" in ctx.text and "main" in ctx.text and "42" in ctx.text
    assert ctx.memory_count == 0  # no memories yet


async def test_includes_memories(mem):
    await mem.add("staging url is x", section="Environment")
    await mem.add("use Redis for cache", section="Decisions")
    svc = SessionContextService(memory_service=mem)
    ctx = svc.build(project_root="/p", branch="main", doc_count=1)
    assert "memory" in ctx.sections
    assert ctx.memory_count == 2
    assert "staging url is x" in ctx.text


async def test_budget_truncates_by_priority(mem):
    # many low-conf memories; tiny budget forces truncation
    for i in range(20):
        await mem.add(f"fact number {i} with some padding text", confidence=0.5)
    await mem.add("HIGH PRIORITY FACT", confidence=1.0)
    svc = SessionContextService(memory_service=mem, budget_tokens=60)  # ~240 chars
    ctx = svc.build(project_root="/p", branch="main", doc_count=1)
    assert ctx.truncated is True
    assert ctx.memory_count < 21
    # highest-confidence memory wins a slot
    assert "HIGH PRIORITY FACT" in ctx.text
    assert ctx.token_estimate <= 60 + 30  # budget + small header slack


def test_token_estimate_set(mem):
    svc = SessionContextService(memory_service=mem)
    ctx = svc.build(project_root="/p", branch="main", doc_count=0)
    assert ctx.token_estimate == len(ctx.text) // 4


async def test_no_memory_service_still_builds():
    svc = SessionContextService(memory_service=None)
    ctx = svc.build(project_root="/p", branch="dev", doc_count=5)
    assert "project_facts" in ctx.sections
    assert "memory" not in ctx.sections
    assert ctx.memory_count == 0
