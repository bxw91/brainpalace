"""Unit tests for the query-time memory boost (Phase 030).

Keyless: builds a QueryService shell (bypassing the heavy __init__) with a stub
memory_service returning canned hits, and exercises _apply_memory_boost's merge
/ floor / dedup / bm25-skip / opt-out logic without embeddings or Chroma.
"""

from __future__ import annotations

from brainpalace_server.models import (
    QueryMode,
    QueryRequest,
    QueryResponse,
    QueryResult,
)
from brainpalace_server.models.memory import MemoryHit
from brainpalace_server.services.query_service import QueryService


class StubMemory:
    def __init__(self, hits):
        self._hits = hits

    async def recall(
        self, query, top_k=3, similarity_threshold=0.0, include_sensitive=False
    ):
        return self._hits[:top_k], 1.0


def _svc(hits):
    qs = QueryService.__new__(QueryService)  # bypass __init__
    qs.memory_service = StubMemory(hits)
    return qs


def _resp(*results):
    return QueryResponse(
        results=list(results), query_time_ms=1.0, total_results=len(results)
    )


def _chunk(cid, score):
    return QueryResult(
        text=f"chunk {cid}",
        source=f"f/{cid}",
        score=score,
        chunk_id=cid,
        source_type="doc",
    )


def _req(mode=QueryMode.HYBRID, top_k=5, use_memory=True):
    return QueryRequest(
        query="staging url", mode=mode, top_k=top_k, use_memory=use_memory
    )


async def test_relevant_memory_ranks_first():
    svc = _svc([MemoryHit(id="mem_1", text="staging url is x", score=0.9)])
    out = await svc._apply_memory_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert out.results[0].chunk_id == "mem_1"
    assert out.results[0].source_type == "memory"
    # 0.9 * 1.5 boost = 1.35 > 0.8
    assert out.results[0].score > out.results[1].score


async def test_below_floor_excluded():
    svc = _svc([MemoryHit(id="mem_low", text="weak", score=0.1)])  # < MEMORY_MIN_SCORE
    out = await svc._apply_memory_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert all(r.source_type != "memory" for r in out.results)


async def test_bm25_mode_skips_boost():
    svc = _svc([MemoryHit(id="mem_1", text="x", score=0.9)])
    req = _req(mode=QueryMode.BM25)
    out = await svc._apply_memory_boost(req, _resp(_chunk("c1", 5.0)))
    assert all(r.source_type != "memory" for r in out.results)


async def test_opt_out_skips_boost():
    svc = _svc([MemoryHit(id="mem_1", text="x", score=0.9)])
    req = _req(use_memory=False)
    out = await svc._apply_memory_boost(req, _resp(_chunk("c1", 0.8)))
    assert all(r.source_type != "memory" for r in out.results)


async def test_no_memory_service_is_noop():
    qs = QueryService.__new__(QueryService)
    qs.memory_service = None
    base = _resp(_chunk("c1", 0.8))
    out = await qs._apply_memory_boost(_req(), base)
    assert out is base


async def test_dedup_against_existing_chunk_id():
    svc = _svc([MemoryHit(id="c1", text="dup id", score=0.9)])
    out = await svc._apply_memory_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert len(out.results) == 1  # memory with same id as a result is not added twice


async def test_truncates_to_top_k():
    svc = _svc([MemoryHit(id="mem_1", text="x", score=0.95)])
    out = await svc._apply_memory_boost(
        _req(top_k=2), _resp(_chunk("c1", 0.9), _chunk("c2", 0.8), _chunk("c3", 0.7))
    )
    assert len(out.results) == 2
    assert out.results[0].chunk_id == "mem_1"


class _Mem:
    def __init__(self, mid, origin):
        self.id = mid
        self.origin = origin


def _svc_with_load(hits, entries):
    qs = _svc(hits)
    qs.memory_service.load = lambda: entries  # type: ignore[attr-defined]
    return qs


async def test_summarization_off_drops_session_derived_memory(monkeypatch):
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda *a, **k: (True, False),  # summarization OFF
    )
    svc = _svc_with_load(
        [
            MemoryHit(id="user_1", text="user fact", score=0.9),
            MemoryHit(id="sess_1", text="promoted decision", score=0.9),
        ],
        [_Mem("user_1", "user"), _Mem("sess_1", "session:abc")],
    )
    out = await svc._apply_memory_boost(_req(), _resp(_chunk("c1", 0.1)))
    mem_ids = {r.chunk_id for r in out.results if r.source_type == "memory"}
    assert mem_ids == {"user_1"}


async def test_summarization_on_keeps_session_derived_memory(monkeypatch):
    monkeypatch.setattr(
        "brainpalace_server.config.session_config.session_recall_flags",
        lambda *a, **k: (True, True),  # summarization ON
    )
    svc = _svc(
        [
            MemoryHit(id="user_1", text="user fact", score=0.9),
            MemoryHit(id="sess_1", text="promoted decision", score=0.9),
        ]
    )
    out = await svc._apply_memory_boost(_req(), _resp(_chunk("c1", 0.1)))
    mem_ids = {r.chunk_id for r in out.results if r.source_type == "memory"}
    assert mem_ids == {"user_1", "sess_1"}
