"""Unit tests for the query-time reference boost (Round 2 Plan C).

Keyless: builds a QueryService shell (bypassing the heavy __init__) with a
stub embedding_generator and stub reference_catalog_store returning canned
(entry, score) hits, and exercises _apply_reference_boost's merge / floor /
dedup / bm25-skip / sensitivity logic without embeddings or Chroma.
"""

from __future__ import annotations

from brainpalace_server.models import (
    QueryMode,
    QueryRequest,
    QueryResponse,
    QueryResult,
)
from brainpalace_server.services.query_service import QueryService
from brainpalace_server.storage.reference_catalog_store import ReferenceEntry


class StubEmbeddingGenerator:
    async def embed_query(self, text):
        return [1.0, 0.0]


class RaisingEmbeddingGenerator:
    async def embed_query(self, text):
        raise RuntimeError("embedder down")


class StubReferenceStore:
    def __init__(self, hits):
        self._hits = hits
        self.last_kwargs = None

    def search_summaries(
        self, query_embedding, top_k=5, domain=None, include_sensitive=False
    ):
        self.last_kwargs = {
            "top_k": top_k,
            "domain": domain,
            "include_sensitive": include_sensitive,
        }
        return self._hits[:top_k]


def _svc(hits, embedder=None):
    qs = QueryService.__new__(QueryService)  # bypass __init__
    qs.reference_catalog_store = StubReferenceStore(hits)
    qs.embedding_generator = embedder or StubEmbeddingGenerator()
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


def _req(mode=QueryMode.HYBRID, top_k=5):
    return QueryRequest(query="staging url", mode=mode, top_k=top_k)


def _entry(rid, sensitivity="normal"):
    return ReferenceEntry(
        id=rid,
        domain="code",
        source="docs",
        source_id="src1",
        pointer="pointer://x",
        summary=f"summary {rid}",
        sensitivity=sensitivity,
    )


async def test_relevant_reference_ranks_first():
    svc = _svc([(_entry("ref_1"), 0.9)])
    out = await svc._apply_reference_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert out.results[0].chunk_id == "ref_1"
    assert out.results[0].source_type == "reference"
    assert out.results[0].metadata["type"] == "reference"
    assert out.results[0].score > out.results[1].score


async def test_below_floor_excluded():
    svc = _svc([(_entry("ref_low"), 0.1)])  # < REFERENCE_MIN_SCORE
    out = await svc._apply_reference_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert all(r.source_type != "reference" for r in out.results)


async def test_bm25_mode_skips_boost():
    svc = _svc([(_entry("ref_1"), 0.9)])
    req = _req(mode=QueryMode.BM25)
    out = await svc._apply_reference_boost(req, _resp(_chunk("c1", 5.0)))
    assert all(r.source_type != "reference" for r in out.results)


async def test_no_reference_store_is_noop():
    qs = QueryService.__new__(QueryService)
    qs.reference_catalog_store = None
    base = _resp(_chunk("c1", 0.8))
    out = await qs._apply_reference_boost(_req(), base)
    assert out is base


async def test_dedup_against_existing_chunk_id():
    svc = _svc([(_entry("c1"), 0.9)])
    out = await svc._apply_reference_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert len(out.results) == 1  # reference with same id as a result not added twice


async def test_truncates_to_top_k():
    svc = _svc([(_entry("ref_1"), 0.95)])
    out = await svc._apply_reference_boost(
        _req(top_k=2), _resp(_chunk("c1", 0.9), _chunk("c2", 0.8), _chunk("c3", 0.7))
    )
    assert len(out.results) == 2
    assert out.results[0].chunk_id == "ref_1"


async def test_embedder_failure_never_breaks_query():
    svc = _svc([(_entry("ref_1"), 0.9)], embedder=RaisingEmbeddingGenerator())
    base = _resp(_chunk("c1", 0.8))
    out = await svc._apply_reference_boost(_req(), base)
    assert out is base


async def test_sensitivity_default_deny_passed_through():
    svc = _svc([(_entry("ref_1"), 0.9)])
    await svc._apply_reference_boost(_req(), _resp(_chunk("c1", 0.8)))
    assert svc.reference_catalog_store.last_kwargs["include_sensitive"] is False


async def test_sensitivity_opt_in_passed_through():
    svc = _svc([(_entry("ref_1"), 0.9)])
    req = QueryRequest(
        query="staging url", mode=QueryMode.HYBRID, top_k=5, include_sensitive=True
    )
    await svc._apply_reference_boost(req, _resp(_chunk("c1", 0.8)))
    assert svc.reference_catalog_store.last_kwargs["include_sensitive"] is True


async def test_reference_boost_preserves_routed_mode():
    """The merge must not drop `routed_mode` (A1).

    Same hazard as the memory boost: this rebuilds a fresh QueryResponse, and
    it is the LAST thing an auto-routed graph query passes through on its way
    to the caller. A dropped field here is invisible in every other test.
    """
    svc = _svc([(_entry("ref_1"), 0.9)])
    resp = QueryResponse(
        results=[_chunk("c1", 0.8)],
        query_time_ms=1.0,
        total_results=1,
        routed_mode=QueryMode.GRAPH,
    )
    out = await svc._apply_reference_boost(_req(), resp)
    assert any(r.source_type == "reference" for r in out.results), "boost must fire"
    assert out.routed_mode == QueryMode.GRAPH
