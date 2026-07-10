"""GET /references + POST /references/search + POST /references/embed-missing.

Minimal FastAPI app wiring the references router + a real
ReferenceCatalogStore on app.state and a patched embedding generator —
mirrors tests/api/test_ingest_endpoints.py's fixture style. Sensitivity is
default-deny: the search endpoint hides non-normal rows unless the request
opts in (mirrors the query path's include_sensitive flag)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.references import router as references_router
from brainpalace_server.providers.exceptions import ProviderError
from brainpalace_server.storage.reference_catalog_store import (
    ReferenceCatalogStore,
    ReferenceEntry,
    ref_id,
)


def _entry(pointer, *, domain="code", sensitivity="normal", summary="a summary"):
    return ReferenceEntry(
        id=ref_id(pointer, "gmail"),
        domain=domain,
        source="gmail",
        source_id="acct-1",
        pointer=pointer,
        summary=summary,
        ingested_at="2026-07-05T00:00:00+00:00",
        sensitivity=sensitivity,
    )


class _FakeEmbedder:
    """embed_query returns a fixed vector; embed_texts echoes per-index vecs."""

    async def embed_query(self, query):
        return [1.0, 0.0]

    async def embed_texts(self, texts, progress_callback=None):
        return [[1.0, 0.0] for _ in texts]


class _BrokenEmbedder:
    async def embed_query(self, query):
        raise ProviderError("no embedding provider configured", "openai")

    async def embed_texts(self, texts, progress_callback=None):
        raise ProviderError("no embedding provider configured", "openai")


def _client(store, embedder=None) -> TestClient:
    app = FastAPI()
    app.include_router(references_router, prefix="/references")
    app.state.reference_catalog_store = store
    ctx = patch(
        "brainpalace_server.api.routers.references.get_embedding_generator",
        return_value=embedder,
    )
    ctx.start()
    return TestClient(app)


@pytest.fixture()
def store(tmp_path):
    s = ReferenceCatalogStore(tmp_path / "refs.db")
    s.upsert(
        [
            _entry("gmail://msg/1", summary="invoice for electricity"),
            _entry("gmail://msg/2", domain="glasses", summary="a receipt"),
            _entry("gmail://msg/secret", sensitivity="private", summary="private note"),
        ]
    )
    s.set_embeddings(
        [
            (ref_id("gmail://msg/1", "gmail"), [1.0, 0.0]),
            (ref_id("gmail://msg/2", "gmail"), [1.0, 0.0]),
            (ref_id("gmail://msg/secret", "gmail"), [1.0, 0.0]),
        ]
    )
    return s


def test_get_references_lists_all(store):
    client = _client(store, _FakeEmbedder())
    r = client.get("/references")
    assert r.status_code == 200, r.text
    refs = r.json()["references"]
    assert len(refs) == 3
    assert {ref["pointer"] for ref in refs} == {
        "gmail://msg/1",
        "gmail://msg/2",
        "gmail://msg/secret",
    }


def test_get_references_filters_by_domain(store):
    client = _client(store, _FakeEmbedder())
    r = client.get("/references", params={"domain": "glasses"})
    assert r.status_code == 200
    refs = r.json()["references"]
    assert [ref["pointer"] for ref in refs] == ["gmail://msg/2"]


def test_search_returns_scored_hits(store):
    client = _client(store, _FakeEmbedder())
    r = client.post("/references/search", json={"query": "power bill", "top_k": 5})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert results  # at least one hit
    assert "score" in results[0]
    # default-deny: the private ref is NOT in the results.
    assert all(hit["pointer"] != "gmail://msg/secret" for hit in results)


def test_search_hides_sensitive_by_default_but_reveals_on_opt_in(store):
    client = _client(store, _FakeEmbedder())
    hidden = client.post("/references/search", json={"query": "note"}).json()["results"]
    assert all(h["pointer"] != "gmail://msg/secret" for h in hidden)

    revealed = client.post(
        "/references/search", json={"query": "note", "include_sensitive": True}
    ).json()["results"]
    assert any(h["pointer"] == "gmail://msg/secret" for h in revealed)


def test_search_503_when_no_embedder(store):
    client = _client(store, _BrokenEmbedder())
    r = client.post("/references/search", json={"query": "x"})
    assert r.status_code == 503


def test_embed_missing_backfills(tmp_path):
    s = ReferenceCatalogStore(tmp_path / "refs.db")
    s.upsert([_entry("gmail://msg/1"), _entry("gmail://msg/2")])
    assert s.count_unembedded() == 2
    client = _client(s, _FakeEmbedder())
    r = client.post("/references/embed-missing")
    assert r.status_code == 200, r.text
    assert r.json()["embedded"] == 2
    assert s.count_unembedded() == 0


def test_endpoints_503_when_store_absent():
    client = _client(None, _FakeEmbedder())
    assert client.get("/references").status_code == 503
    assert client.post("/references/search", json={"query": "x"}).status_code == 503
    assert client.post("/references/embed-missing").status_code == 503
