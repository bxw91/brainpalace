"""Plan 4 Task 3 — executors gate on lifespan-resolved mode + H2 lock; the
/extraction/pending endpoint surfaces docs only for subagent/auto + graphrag."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.extraction import router
from brainpalace_server.services.doc_extraction_adapter import DocExtractionAdapter
from brainpalace_server.storage.extraction_pending import DocPendingStore


@pytest.mark.parametrize(
    "mode,lock,ready",
    [
        ("provider", True, True),
        ("auto", True, True),
        ("provider", False, False),  # H2: no lock ⇒ not ready
        ("subagent", True, False),
        ("off", True, False),
    ],
)
def test_doc_adapter_ready(mode, lock, ready):
    a = DocExtractionAdapter(
        store=object(),
        graph_store=object(),
        provider_factory=lambda: object(),
        graphrag_enabled=True,
        grace_hours=24,
        mode=mode,
        provider_enabled=lock,
    )
    assert a.is_ready is ready


def test_doc_adapter_not_ready_without_graphrag():
    a = DocExtractionAdapter(
        store=object(),
        graph_store=object(),
        provider_factory=lambda: object(),
        graphrag_enabled=False,
        mode="provider",
        provider_enabled=True,
    )
    assert a.is_ready is False


@pytest.mark.asyncio
async def test_auto_grace_defers_until_eligible(tmp_path):
    # Task 4f: in auto the provider drains only once the subagent has been absent
    # a whole grace window (anchored on last-drain + server_start, gated on the
    # first request) — NOT on chunk created_at.
    import time

    s = DocPendingStore(tmp_path / "p.db")
    s.mark_pending("c1", "just indexed")

    # Cold start (no request seen) → never eligible, even past grace.
    a_cold = DocExtractionAdapter(
        store=s,
        graph_store=object(),
        provider_factory=lambda: object(),
        graphrag_enabled=True,
        mode="auto",
        provider_enabled=True,
        grace_hours=24,
        project_root=str(tmp_path),
        server_start_ts=time.time() - 48 * 3600,
        first_request_seen=lambda: False,
    )
    assert await a_cold.select_pending(10) == []

    # Request seen + past grace since start + no recent subagent drain → drains.
    a_live = DocExtractionAdapter(
        store=s,
        graph_store=object(),
        provider_factory=lambda: object(),
        graphrag_enabled=True,
        mode="auto",
        provider_enabled=True,
        grace_hours=24,
        project_root=str(tmp_path),
        server_start_ts=time.time() - 48 * 3600,
        first_request_seen=lambda: True,
    )
    assert [cid for cid, _ in await a_live.select_pending(10)] == ["c1"]

    # A recent subagent drain (last-drain stamp) defers the provider again.
    state = tmp_path / ".brainpalace" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "last-drain").write_text(str(time.time()), encoding="utf-8")
    assert await a_live.select_pending(10) == []


@pytest.mark.asyncio
async def test_provider_mode_drains_immediately(tmp_path):
    # provider (not auto) ⇒ no grace; drains the fresh chunk now.
    s = DocPendingStore(tmp_path / "p.db")
    s.mark_pending("c1", "alpha")
    a = DocExtractionAdapter(
        store=s,
        graph_store=object(),
        provider_factory=lambda: object(),
        graphrag_enabled=True,
        mode="provider",
        provider_enabled=True,
        grace_hours=24,
    )
    assert [cid for cid, _ in await a.select_pending(10)] == ["c1"]


@pytest.mark.parametrize(
    "mode,surfaces",
    [("subagent", True), ("auto", True), ("provider", False), ("off", False)],
)
def test_pending_surfaces_docs(tmp_path, mode, surfaces):
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    s = DocPendingStore(tmp_path / "p.db")
    s.mark_pending("c1", "alpha")
    app.state.doc_pending_store = s
    app.state.project_root = str(tmp_path)
    app.state.extraction_archive_dir = str(tmp_path)
    app.state.extraction_mode_doc = mode
    app.state.graphrag_enabled = True
    body = TestClient(app).get("/extraction/pending?limit=10&source=doc").json()
    assert any(i["source"] == "doc" for i in body["items"]) is surfaces
    # doc_pending_total always reported (spec §12), independent of surfacing.
    assert body["doc_pending_total"] == 1


@pytest.mark.parametrize(
    "mode,surfaces",
    [("subagent", True), ("auto", True), ("provider", False), ("off", False)],
)
def test_pending_surfaces_sessions(tmp_path, monkeypatch, mode, surfaces):
    # Sessions must gate on extraction_mode_session exactly like docs: off /
    # provider ⇒ the free subagent is NOT nudged; subagent / auto ⇒ surfaced.
    monkeypatch.setattr(
        "brainpalace_server.api.routers.extraction.pending_sessions",
        lambda *a, **k: [("s1", "/a/s1.jsonl")],
    )
    app = FastAPI()
    app.include_router(router, prefix="/extraction")
    app.state.project_root = str(tmp_path)
    app.state.extraction_archive_dir = str(tmp_path)
    app.state.extraction_mode_session = mode
    body = TestClient(app).get("/extraction/pending?limit=10&source=session").json()
    assert any(i["source"] == "session" for i in body["items"]) is surfaces
