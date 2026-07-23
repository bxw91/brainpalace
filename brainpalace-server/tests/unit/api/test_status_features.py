"""Phase 5.1 — /status exposes a consolidated per-feature block."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brainpalace_server.api.routers.health import router


def _client_with_extraction(
    *,
    extraction_mode_doc="off",
    graphrag_enabled=False,
    extraction_provider_enabled=False,
    summarization_available=False,
    summarization_label=None,
    doc_pending_count=0,
):
    """Minimal app state for testing the doc_graph_extraction feature block."""
    app = FastAPI()
    app.include_router(router)

    backend = MagicMock()
    backend.is_initialized = True

    async def _get_count(where=None):
        return 0

    backend.get_count = AsyncMock(side_effect=_get_count)

    indexing_service = MagicMock()
    indexing_service.get_status = AsyncMock(
        return_value={
            "status": "idle",
            "total_doc_chunks": 0,
            "total_code_chunks": 0,
            "indexed_folders": [],
            "supported_languages": [],
            "graph_index": {"enabled": False},
            "completed_at": None,
        }
    )
    indexing_service.get_document_count = AsyncMock(return_value=0)
    indexing_service.get_document_counts_by_type = AsyncMock(
        return_value={"code": 0, "doc": 0, "total": 0}
    )

    app.state.indexing_service = indexing_service
    app.state.storage_backend = backend
    app.state.job_service = None
    app.state.vector_store = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    app.state.file_watcher_service = SimpleNamespace(
        is_running=False, watched_folder_count=0
    )
    app.state.session_indexing_config = SimpleNamespace(
        enabled=False, archive=SimpleNamespace(retain_days=0)
    )
    app.state.session_index_enabled = False
    app.state.session_archive_enabled = False
    app.state.session_reconciler = None
    app.state.memory_service = None
    app.state.session_archive_service = None

    # Extraction-specific state stashed at lifespan (Task 2)
    app.state.extraction_mode_doc = extraction_mode_doc
    app.state.graphrag_enabled = graphrag_enabled
    app.state.extraction_provider_enabled = extraction_provider_enabled
    app.state.summarization_available = summarization_available
    app.state.summarization_label = summarization_label

    # Pending store stub with configurable count
    if doc_pending_count > 0:
        pending_store = MagicMock()
        pending_store.count_pending = MagicMock(return_value=doc_pending_count)
        app.state.doc_pending_store = pending_store
    else:
        app.state.doc_pending_store = None

    return TestClient(app)


def _client(
    *,
    session_enabled,
    session_running,
    curated,
    session_chunks,
    archive_stats=None,
    archive_enabled=None,
    ingest_chunks=0,
):
    app = FastAPI()
    app.include_router(router)

    backend = MagicMock()
    backend.is_initialized = True

    async def _get_count(where=None):
        if where and where.get("source_type") == "session_turn":
            return session_chunks
        if where and where.get("source_type") == "ingest":
            return ingest_chunks
        return 42  # total_chunks

    backend.get_count = AsyncMock(side_effect=_get_count)

    indexing_service = MagicMock()
    indexing_service.get_status = AsyncMock(
        return_value={
            "status": "idle",
            "total_doc_chunks": 0,
            "total_code_chunks": 0,
            "indexed_folders": [],
            "supported_languages": [],
            "graph_index": {"enabled": False},
            "completed_at": None,
        }
    )
    indexing_service.get_document_count = AsyncMock(return_value=3)
    indexing_service.get_document_counts_by_type = AsyncMock(
        return_value={"code": 2, "doc": 1, "total": 3}
    )

    app.state.indexing_service = indexing_service
    app.state.storage_backend = backend
    app.state.job_service = None
    app.state.vector_store = None
    app.state.embedding_cache = None
    app.state.query_cache = None
    # health.py reads file_watcher_service (.is_running / .watched_folder_count).
    app.state.file_watcher_service = SimpleNamespace(
        is_running=True, watched_folder_count=2
    )
    app.state.session_indexing_config = SimpleNamespace(
        enabled=session_enabled, archive=SimpleNamespace(retain_days=0)
    )
    # Resolved capability flags (archive + index independent).
    app.state.session_index_enabled = session_enabled
    app.state.session_archive_enabled = (
        session_enabled if archive_enabled is None else archive_enabled
    )
    app.state.session_reconciler = SimpleNamespace(is_running=session_running)
    app.state.memory_service = SimpleNamespace(load=lambda: [object()] * curated)
    if archive_stats is None:
        app.state.session_archive_service = None
    else:
        app.state.session_archive_service = SimpleNamespace(stats=lambda: archive_stats)
    return TestClient(app)


def test_status_reports_feature_block():
    client = _client(
        session_enabled=True, session_running=True, curated=5, session_chunks=7
    )
    data = client.get("/status").json()
    # Code/doc split from get_document_counts_by_type propagates to the response.
    assert data["total_documents"] == 3
    assert data["code_documents"] == 2
    assert data["doc_documents"] == 1
    feats = data["features"]

    assert feats["doc_indexing"]["active"] is True
    assert feats["doc_indexing"]["total_chunks"] == 42
    assert feats["doc_indexing"]["total_documents"] == 3
    assert feats["file_watcher"]["enabled"] is True
    assert feats["file_watcher"]["watched_folders"] == 2
    assert feats["session_memory"]["enabled"] is True
    assert feats["session_memory"]["watcher_running"] is True
    assert feats["session_memory"]["session_chunks"] == 7
    assert feats["session_memory"]["curated_memories"] == 5
    assert feats["session_memory"]["archived_sessions"] == 0
    assert feats["session_memory"]["archived_bytes"] == 0
    assert feats["session_memory"]["tombstoned"] == 0
    # Archive is its own independent feature block.
    assert feats["session_archive"]["enabled"] is True
    assert feats["session_archive"]["retain_days"] == 0
    assert feats["graph_index"]["enabled"] is False


def test_status_reports_text_ingest_count():
    # Ingested-text chunks (source_type="ingest") get their own count block,
    # separate from total_documents (which stays folder-manifest-derived).
    client = _client(
        session_enabled=False,
        session_running=False,
        curated=0,
        session_chunks=0,
        ingest_chunks=5,
    )
    data = client.get("/status").json()
    assert data["text_ingest"]["chunks"] == 5
    # Not folded into folder-manifest document totals.
    assert data["total_documents"] == 3


def test_status_text_ingest_zero_when_none():
    client = _client(
        session_enabled=False, session_running=False, curated=0, session_chunks=0
    )
    data = client.get("/status").json()
    assert data["text_ingest"]["chunks"] == 0


def test_status_feature_block_session_disabled():
    client = _client(
        session_enabled=False, session_running=False, curated=0, session_chunks=0
    )
    feats = client.get("/status").json()["features"]
    assert feats["session_memory"]["enabled"] is False
    assert feats["session_memory"]["watcher_running"] is False


def test_archive_on_index_off_independent():
    # Existing-project shape: archive ON, index OFF — independent feature rows.
    client = _client(
        session_enabled=False,
        session_running=False,
        curated=0,
        session_chunks=0,
        archive_enabled=True,
        archive_stats={
            "archived_sessions": 4,
            "archived_files": 5,
            "archived_bytes": 999,
            "tombstoned": 0,
        },
    )
    feats = client.get("/status").json()["features"]
    assert feats["session_memory"]["enabled"] is False
    assert feats["session_archive"]["enabled"] is True
    assert feats["session_archive"]["archived_files"] == 5


def test_status_reports_lsp_and_git_index_features():
    client = _client(
        session_enabled=True, session_running=True, curated=0, session_chunks=0
    )
    feats = client.get("/status").json()["features"]

    assert "lsp" in feats
    assert isinstance(feats["lsp"]["enabled"], bool)
    assert "languages" in feats["lsp"]

    assert "git_index" in feats
    assert isinstance(feats["git_index"]["enabled"], bool)
    assert "commit_count" in feats["git_index"]


def test_status_lsp_languages_reflect_env(monkeypatch):
    from brainpalace_server.config.settings import get_settings

    monkeypatch.setenv("BRAINPALACE_LSP_LANGUAGES", "python, go")
    get_settings.cache_clear()
    try:
        client = _client(
            session_enabled=True, session_running=True, curated=0, session_chunks=0
        )
        lsp = client.get("/status").json()["features"]["lsp"]
        assert lsp["enabled"] is True
        assert lsp["languages"] == ["go", "python"]  # sorted() alphabetical
    finally:
        get_settings.cache_clear()


def test_session_memory_includes_archive_counts():
    client = _client(
        session_enabled=True,
        session_running=True,
        curated=0,
        session_chunks=2,
        archive_stats={
            "archived_sessions": 2,
            "archived_files": 3,
            "archived_bytes": 1234,
            "tombstoned": 1,
        },
    )
    sm = client.get("/status").json()["features"]["session_memory"]
    assert sm["archived_sessions"] == 2
    assert sm["archived_files"] == 3
    assert sm["archived_bytes"] == 1234
    assert sm["tombstoned"] == 1


def test_session_archive_reports_pending_backlog(monkeypatch):
    # The to-summarize backlog (un-distilled archived sessions) is surfaced on
    # the session_archive block, regardless of mode (like doc "un-graphed").
    monkeypatch.setattr(
        "brainpalace_server.services.session_distill_service.pending_sessions",
        lambda *a, **k: [("s1", "/a/s1"), ("s2", "/a/s2"), ("s3", "/a/s3")],
    )
    client = _client(
        session_enabled=False,
        session_running=False,
        curated=0,
        session_chunks=0,
        archive_enabled=True,
        archive_stats={
            "archived_sessions": 5,
            "archived_files": 5,
            "archived_bytes": 100,
            "tombstoned": 0,
        },
    )
    client.app.state.project_root = "/proj"
    client.app.state.extraction_archive_dir = "/proj/.brainpalace/sessions"
    sa = client.get("/status").json()["features"]["session_archive"]
    assert sa["pending_summarization"] == 3


def test_session_archive_pending_defaults_zero_without_root(monkeypatch):
    # No project_root/archive_dir wired ⇒ advisory backlog defaults to 0 and the
    # status call never fails (best-effort).
    monkeypatch.setattr(
        "brainpalace_server.services.session_distill_service.pending_sessions",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("must not be called")),
    )
    client = _client(
        session_enabled=True,
        session_running=True,
        curated=0,
        session_chunks=0,
        archive_enabled=True,
        archive_stats={
            "archived_sessions": 1,
            "archived_files": 1,
            "archived_bytes": 1,
            "tombstoned": 0,
        },
    )
    sa = client.get("/status").json()["features"]["session_archive"]
    assert sa["pending_summarization"] == 0


# ---------------------------------------------------------------------------
# Task 5 — doc_graph_extraction feature block (C2 + M1 + spec §12)
# ---------------------------------------------------------------------------


def test_features_doc_graph_extraction_off_no_pending():
    client = _client_with_extraction(extraction_mode_doc="off", graphrag_enabled=True)
    dge = client.get("/status").json()["features"]["doc_graph_extraction"]
    assert dge["state"] == "off"
    assert dge["pending"] == 0
    assert dge["ungraphed"] is False  # M1: ungraphed only when off AND pending > 0


def test_features_doc_graph_extraction_off_with_pending():
    # M1: off + pending → ungraphed=True, NOT "pending" in wording
    client = _client_with_extraction(
        extraction_mode_doc="off", graphrag_enabled=True, doc_pending_count=5
    )
    dge = client.get("/status").json()["features"]["doc_graph_extraction"]
    assert dge["state"] == "off"
    assert dge["pending"] == 5
    assert dge["ungraphed"] is True


def test_features_doc_graph_extraction_subagent():
    client = _client_with_extraction(
        extraction_mode_doc="subagent", graphrag_enabled=True, doc_pending_count=3
    )
    dge = client.get("/status").json()["features"]["doc_graph_extraction"]
    assert dge["state"] == "subagent"
    assert dge["pending"] == 3
    assert dge["ungraphed"] is False


def test_features_doc_graph_extraction_provider_active():
    client = _client_with_extraction(
        extraction_mode_doc="provider",
        graphrag_enabled=True,
        extraction_provider_enabled=True,
        summarization_available=True,
        summarization_label="anthropic:claude-haiku-4-5",
        doc_pending_count=2,
    )
    dge = client.get("/status").json()["features"]["doc_graph_extraction"]
    assert dge["state"] == "provider"
    assert dge["provider"] == "anthropic:claude-haiku-4-5"
    assert dge["pending"] == 2


def test_features_doc_graph_extraction_provider_unavailable():
    # provider/auto requested but no usable provider or lock is off
    client = _client_with_extraction(
        extraction_mode_doc="provider",
        graphrag_enabled=True,
        extraction_provider_enabled=False,
        summarization_available=False,
    )
    dge = client.get("/status").json()["features"]["doc_graph_extraction"]
    assert dge["state"] == "unavailable"


def test_features_doc_graph_extraction_state_is_valid():
    # Generic: state must always be one of the 4 values
    for mode in ("off", "subagent", "provider", "auto"):
        client = _client_with_extraction(
            extraction_mode_doc=mode, graphrag_enabled=True
        )
        dge = client.get("/status").json()["features"]["doc_graph_extraction"]
        assert dge["state"] in ("off", "subagent", "provider", "unavailable")
    assert isinstance(dge["pending"], int)
    assert isinstance(dge["ungraphed"], bool)


# ---------------------------------------------------------------------------
# Phase 6.5a — ranking (doc_weight) feature block
# ---------------------------------------------------------------------------


def test_features_ranking_defaults_half_without_state():
    # No app.state.ranking_config wired (e.g. older test client) ⇒ default 0.5.
    client = _client(
        session_enabled=True, session_running=True, curated=0, session_chunks=0
    )
    ranking = client.get("/status").json()["features"]["ranking"]
    assert ranking["doc_weight"] == 0.5


def test_features_ranking_reflects_configured_weight():
    from brainpalace_server.config.ranking_config import RankingConfig

    client = _client(
        session_enabled=True, session_running=True, curated=0, session_chunks=0
    )
    client.app.state.ranking_config = RankingConfig(doc_weight=0.2)
    ranking = client.get("/status").json()["features"]["ranking"]
    assert ranking["doc_weight"] == 0.2


def test_session_archive_reports_detected_tools():
    """`features.session_archive.tools` mirrors the resolved sources."""
    from types import SimpleNamespace

    client = _client_with_extraction()
    client.app.state.session_sources = [
        SimpleNamespace(slug="claude-code", directory="/x"),
        SimpleNamespace(slug="codex", directory="/y"),
    ]

    features = client.get("/status").json()["features"]

    assert features["session_archive"]["tools"] == ["claude-code", "codex"]


def test_session_archive_tools_prefers_the_live_provider():
    """A provider re-resolves per call, so a tool installed after startup
    shows up without a restart; the snapshot is only the fallback."""
    from types import SimpleNamespace

    client = _client_with_extraction()
    client.app.state.session_sources = [SimpleNamespace(slug="claude-code")]
    client.app.state.session_sources_provider = lambda: [
        SimpleNamespace(slug="claude-code"),
        SimpleNamespace(slug="antigravity"),
    ]

    features = client.get("/status").json()["features"]

    assert features["session_archive"]["tools"] == ["claude-code", "antigravity"]


def test_session_archive_tools_defaults_to_empty():
    client = _client_with_extraction()
    features = client.get("/status").json()["features"]
    assert features["session_archive"]["tools"] == []


def test_status_includes_report():
    client = _client(
        session_enabled=False, session_running=False, curated=0, session_chunks=0
    )
    data = client.get("/status").json()
    assert "report" in data
    keys = {row["key"] for row in data["report"]["rows"]}
    assert {"server_version", "total_documents", "total_chunks"} <= keys
    assert isinstance(data["report"]["alerts"], list)
