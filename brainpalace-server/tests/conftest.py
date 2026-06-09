"""Pytest configuration and fixtures for doc-serve-server tests."""

import os
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# Set test environment variables before importing app
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["DEBUG"] = "true"

# Process-wide state dir, set BEFORE any app import, so nothing ever falls back
# to ``CWD/.brainpalace`` — not at import/collection time, not from a lingering
# lifespan worker thread, not from the repo's real index. The per-test
# ``_isolate_state_dir`` fixture layers per-test isolation on top of this.
os.environ.setdefault(
    "BRAINPALACE_STATE_DIR", tempfile.mkdtemp(prefix="bp_test_state_")
)


@pytest.fixture
def temp_docs_dir() -> Generator[Path, None, None]:
    """Create a temporary directory with sample documents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        docs_path = Path(tmpdir)

        # Create sample markdown files
        (docs_path / "doc1.md").write_text(
            "# Introduction\n\nThis is a sample document about Python programming.\n"
            "Python is a versatile language used for web development, data science, "
            "and automation.\n"
        )
        (docs_path / "doc2.md").write_text(
            "# FastAPI Guide\n\nFastAPI is a modern web framework for building APIs.\n"
            "It provides automatic OpenAPI documentation and type validation.\n"
        )
        (docs_path / "subdir").mkdir()
        (docs_path / "subdir" / "doc3.md").write_text(
            "# Advanced Topics\n\nThis document covers advanced programming concepts.\n"
            "Including async/await patterns and dependency injection.\n"
        )

        yield docs_path


@pytest.fixture
def temp_chroma_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for Chroma persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_embedding_generator():
    """Mock embedding generator that returns fake embeddings."""
    mock = AsyncMock()

    # Return a fake embedding vector (dimension 3072 to match text-embedding-3-large)
    fake_embedding = [0.1] * 3072
    mock.embed_query.return_value = fake_embedding
    mock.embed_chunks.return_value = [fake_embedding]
    mock.embed_texts.return_value = [fake_embedding]

    return mock


@pytest.fixture
def mock_vector_store():
    """Mock vector store for unit tests."""
    mock = MagicMock()
    mock.is_initialized = True
    mock.initialize = AsyncMock()
    mock.add_documents = AsyncMock(return_value=1)
    mock.similarity_search = AsyncMock(return_value=[])
    mock.get_count = AsyncMock(return_value=10)
    mock.reset = AsyncMock()
    return mock


@pytest.fixture(autouse=True)
def _isolate_state_dir(tmp_path_factory, monkeypatch):
    """Point all state at a throwaway dir so tests never pollute CWD.

    The app lifespan and storage services (JobQueue, EmbeddingCache,
    SessionArchive, vector/bm25 stores) resolve their paths from
    ``BRAINPALACE_STATE_DIR``. Without this, integration tests that boot the
    real lifespan via ``TestClient`` fall back to ``CWD/.brainpalace`` and
    create a stray ``brainpalace-server/.brainpalace`` (or worse, write the
    repo's real index). Isolate it per test.
    """
    state = tmp_path_factory.mktemp("bp_state")
    monkeypatch.setenv("BRAINPALACE_STATE_DIR", str(state))
    yield


@pytest.fixture(autouse=True)
def _isolate_global_config(tmp_path_factory, monkeypatch):
    """Empty the GLOBAL (XDG / legacy-home) config layer for every test.

    Config now resolves ``code < global < project`` (load_merged_config_dict),
    so without this the dev machine's real ``~/.config/brainpalace/config.yaml``
    would be layered under every test's settings and make provider-config
    assertions non-deterministic. Point XDG_CONFIG_HOME + HOME at empty temp
    dirs so the global layer is absent unless a test writes one explicitly.
    """
    xdg = tmp_path_factory.mktemp("bp_xdg")
    home = tmp_path_factory.mktemp("bp_home")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BRAINPALACE_CONFIG", raising=False)
    yield


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset service singletons before each test."""

    import brainpalace_server.indexing.bm25_index as bm25_mod
    import brainpalace_server.indexing.graph_extractors as extractor_mod
    import brainpalace_server.indexing.graph_index as graph_index_mod
    import brainpalace_server.services.indexing_service as idx_mod
    import brainpalace_server.services.query_service as query_mod
    import brainpalace_server.storage.factory as factory_mod
    import brainpalace_server.storage.graph_store as graph_mod

    bm25_mod._bm25_manager = None
    idx_mod._indexing_service = None
    query_mod._query_service = None
    graph_mod._graph_store_manager = None
    graph_mod.GraphStoreManager._instance = None
    graph_index_mod._graph_index_manager = None
    extractor_mod._llm_extractor = None
    extractor_mod._code_extractor = None
    # Reset storage backend singleton (Phase 5)
    factory_mod._storage_backend = None
    factory_mod._backend_type = None

    yield

    bm25_mod._bm25_manager = None
    idx_mod._indexing_service = None
    query_mod._query_service = None
    graph_mod._graph_store_manager = None
    graph_mod.GraphStoreManager._instance = None
    graph_index_mod._graph_index_manager = None
    extractor_mod._llm_extractor = None
    extractor_mod._code_extractor = None
    # Reset storage backend singleton (Phase 5)
    factory_mod._storage_backend = None
    factory_mod._backend_type = None


@pytest.fixture
def mock_bm25_manager():
    """Mock BM25 manager for unit tests."""
    mock = MagicMock()
    mock.is_initialized = True
    mock.initialize = MagicMock()
    mock.build_index = MagicMock()
    mock.get_retriever = MagicMock()
    mock.reset = MagicMock()
    # Add search_with_filters for new StorageBackendProtocol path (Phase 5)
    mock.search_with_filters = AsyncMock(return_value=[])

    retriever_mock = AsyncMock()
    retriever_mock.aretrieve = AsyncMock(return_value=[])
    mock.get_retriever.return_value = retriever_mock

    return mock


@pytest.fixture
def app_with_mocks(mock_vector_store, mock_embedding_generator, mock_bm25_manager):
    """Create FastAPI app with mocked dependencies.

    Sets up app.state with mock services to match the DI pattern
    used by route handlers (request.app.state.<service>).
    """
    with (
        patch(
            "brainpalace_server.storage.get_vector_store",
            return_value=mock_vector_store,
        ),
        patch(
            "brainpalace_server.storage.initialize_vector_store",
            new_callable=AsyncMock,
            return_value=mock_vector_store,
        ),
        patch(
            "brainpalace_server.indexing.get_embedding_generator",
            return_value=mock_embedding_generator,
        ),
        patch(
            "brainpalace_server.indexing.get_bm25_manager",
            return_value=mock_bm25_manager,
        ),
    ):
        from brainpalace_server.api.main import app
        from brainpalace_server.services import IndexingService, QueryService

        # Populate app.state with mock-backed services for DI
        app.state.vector_store = mock_vector_store
        app.state.bm25_manager = mock_bm25_manager
        app.state.indexing_service = IndexingService(
            vector_store=mock_vector_store,
            bm25_manager=mock_bm25_manager,
        )
        app.state.query_service = QueryService(
            vector_store=mock_vector_store,
            embedding_generator=mock_embedding_generator,
            bm25_manager=mock_bm25_manager,
        )
        app.state.mode = "project"
        app.state.instance_id = None
        app.state.project_id = None
        app.state.active_projects = None

        yield app


@pytest.fixture
def client(app_with_mocks) -> Generator[TestClient, None, None]:
    """Create synchronous test client."""
    with TestClient(app_with_mocks) as client:
        yield client


@pytest.fixture
async def async_client(app_with_mocks) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    transport = ASGITransport(app=app_with_mocks)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# Sample test data
@pytest.fixture
def sample_query_request() -> dict:
    """Sample query request payload."""
    return {
        "query": "How do I use FastAPI?",
        "top_k": 5,
        "similarity_threshold": 0.7,
    }


@pytest.fixture
def sample_index_request(temp_docs_dir) -> dict:
    """Sample index request payload."""
    return {
        "folder_path": str(temp_docs_dir),
        "chunk_size": 512,
        "chunk_overlap": 50,
        "recursive": True,
    }
