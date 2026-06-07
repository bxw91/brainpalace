"""FastAPI application entry point.

This module provides the BrainPalace RAG server, a FastAPI application
for document indexing and semantic search.

Note: This server assumes a single uvicorn worker process. If running
multiple workers, ensure only one worker handles indexing jobs by using
the single-worker model or a separate job processor service.
"""

import asyncio
import logging
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brainpalace_server.config.provider_config import ProviderSettings

import click
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from brainpalace_server import __version__
from brainpalace_server.config import settings
from brainpalace_server.config.bm25_config import load_bm25_config
from brainpalace_server.config.provider_config import (
    ValidationSeverity,
    clear_settings_cache,
    has_critical_errors,
    load_provider_settings,
    validate_provider_config,
)
from brainpalace_server.indexing.bm25_index import BM25IndexManager, set_bm25_manager
from brainpalace_server.job_queue import (
    JobQueueService,
    JobQueueStore,
    JobWorker,
    select_reenqueue_candidates,
)
from brainpalace_server.locking import (
    acquire_lock,
    cleanup_stale,
    is_stale,
    release_lock,
)
from brainpalace_server.project_root import resolve_project_root
from brainpalace_server.runtime import RuntimeState, delete_runtime, write_runtime
from brainpalace_server.services import FolderManager, IndexingService, QueryService
from brainpalace_server.storage import (
    VectorStoreManager,
    get_effective_backend_type,
    get_storage_backend,
    set_vector_store,
)
from brainpalace_server.storage_paths import resolve_state_dir, resolve_storage_paths

from .routers import (
    cache_router,
    folders_router,
    health_router,
    index_router,
    jobs_router,
    query_router,
    runtime_router,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Module-level state for multi-instance mode
_runtime_state: RuntimeState | None = None
_state_dir: Path | None = None

# Module-level reference to job worker for cleanup
_job_worker: JobWorker | None = None

# Module-level reference to file watcher service for cleanup
_file_watcher: object = None


def _silence_chromadb_telemetry() -> None:
    """Hard-disable ChromaDB's PostHog product telemetry.

    ChromaDB 0.5.x calls ``posthog.capture()`` with positional arguments that
    posthog >= 3 rejects (``capture() takes 1 positional argument but 3 were
    given``), logging a spurious ``ERROR`` for every telemetry event on startup
    and indexing. The documented off-switches — ``anonymized_telemetry=False``
    and the ``ANONYMIZED_TELEMETRY`` env var — are *not* honored in 0.5.23, so
    we neutralize the telemetry client directly (no-op ``capture``) and raise
    the relevant loggers above ERROR as a fallback. No telemetry is sent either
    way; this only removes the noise. Safe across chromadb versions: the
    monkeypatch is best-effort and the env/logger settings are harmless.
    """
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    try:
        from chromadb.telemetry.product.posthog import Posthog

        # Replace the bound capture with a no-op accepting any signature so
        # neither the 0.5.x positional call nor any future shape can raise.
        Posthog.capture = lambda self, *args, **kwargs: None  # type: ignore[method-assign]
    except Exception:  # pragma: no cover - chromadb internals may move
        pass
    for name in ("chromadb.telemetry", "posthog", "backoff"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _build_provider_fingerprint() -> str:
    """Build a stable provider:model:dimensions fingerprint string.

    Used by the embedding cache to detect provider or model changes on
    startup (ECACHE-04 auto-wipe).

    Returns:
        Fingerprint string of the form ``"provider:model:dimensions"``,
        e.g. ``"openai:text-embedding-3-large:3072"``.
        Returns ``"unknown:unknown:0"`` on any configuration error.
    """
    try:
        ps = load_provider_settings()
        from brainpalace_server.providers.factory import ProviderRegistry

        provider = ProviderRegistry.get_embedding_provider(ps.embedding)
        dims = provider.get_dimensions()
        return f"{ps.embedding.provider}:{ps.embedding.model}:{dims}"
    except Exception as exc:
        logger.warning("Failed to build provider fingerprint: %s", exc)
        return "unknown:unknown:0"


async def check_embedding_compatibility(
    vector_store: VectorStoreManager,
) -> str | None:
    """Check if current embedding config matches existing index.

    Args:
        vector_store: Initialized vector store manager

    Returns:
        Warning message if mismatch detected, None if compatible
    """
    try:
        stored_metadata = await vector_store.get_embedding_metadata()
        if stored_metadata is None:
            return None  # No existing index

        # Get current config
        provider_settings = load_provider_settings()
        from brainpalace_server.providers.factory import ProviderRegistry

        embedding_provider = ProviderRegistry.get_embedding_provider(
            provider_settings.embedding
        )
        current_dimensions = embedding_provider.get_dimensions()
        current_provider = str(provider_settings.embedding.provider)
        current_model = provider_settings.embedding.model

        # Check for mismatch
        if (
            stored_metadata.dimensions != current_dimensions
            or stored_metadata.provider != current_provider
            or stored_metadata.model != current_model
        ):
            return (
                f"Embedding provider mismatch: index was created with "
                f"{stored_metadata.provider}/{stored_metadata.model} "
                f"({stored_metadata.dimensions}d), but current config uses "
                f"{current_provider}/{current_model} ({current_dimensions}d). "
                f"Queries may return incorrect results. "
                f"Re-index with --force to update."
            )
        return None
    except Exception as e:
        logger.warning(f"Failed to check embedding compatibility: {e}")
        return None


def _apply_graphrag_yaml_overrides(provider_settings: "ProviderSettings") -> None:
    """Apply graphrag: YAML config to GRAPH_* settings — env vars win.

    For each GRAPH_* setting, if the corresponding environment variable is
    NOT set, and the graphrag: YAML section provided a value, copy the YAML
    value onto the module-level `settings` singleton. An explicit env var
    always takes precedence (12-factor): YAML only fills unset slots.

    `Settings` is a module-level singleton read directly by service
    constructors, so mutating it here — before those services are built —
    propagates correctly.

    Ordering constraint: this MUST run before any code that calls
    `get_graph_index_manager()` / `GraphStoreManager.get_instance()`. Those
    singletons capture `GRAPH_STORE_TYPE` and `GRAPH_INDEX_PATH` into
    instance fields at construction time, so a later override of those
    settings would not reach an already-built graph manager. In normal
    server startup the graph manager is constructed during `IndexingService`
    init, well after this call — the lifespan call site satisfies this.
    """
    graphrag = provider_settings.graphrag
    # (env var name on Settings, attribute name on GraphRAGConfig)
    mapping: list[tuple[str, str]] = [
        ("ENABLE_GRAPH_INDEX", "enabled"),
        ("GRAPH_STORE_TYPE", "store_type"),
        ("GRAPH_INDEX_PATH", "index_path"),
        ("GRAPH_EXTRACTION_MODEL", "extraction_model"),
        ("GRAPH_MAX_TRIPLETS_PER_CHUNK", "max_triplets_per_chunk"),
        ("GRAPH_USE_CODE_METADATA", "use_code_metadata"),
        ("GRAPH_USE_LLM_EXTRACTION", "use_llm_extraction"),
        ("GRAPH_TRAVERSAL_DEPTH", "traversal_depth"),
        ("GRAPH_RRF_K", "rrf_k"),
        ("GRAPH_DOC_EXTRACTOR", "doc_extractor"),
        ("GRAPH_LANGEXTRACT_PROVIDER", "langextract_provider"),
        ("GRAPH_LANGEXTRACT_MODEL", "langextract_model"),
    ]
    applied: list[str] = []
    for env_name, yaml_attr in mapping:
        if env_name in os.environ:
            continue  # env-wins: explicit env var overrides YAML
        value = getattr(graphrag, yaml_attr, None)
        if value is not None:
            setattr(settings, env_name, value)
            applied.append(f"{env_name}={value}")
    if applied:
        logger.info(
            "Applied graphrag: YAML overrides (env vars take precedence): %s",
            ", ".join(applied),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager.

    Initializes services and stores them on app.state for dependency
    injection via request.app.state in route handlers.

    In per-project mode:
    - Resolves project root and state directory
    - Acquires lock (with stale detection)
    - Writes runtime.json with server info
    - Initializes job queue system
    - Cleans up on shutdown
    """
    global _runtime_state, _state_dir, _job_worker, _file_watcher

    logger.info("Starting BrainPalace RAG server...")

    # Record server start time for the /runtime/ endpoint (B8).
    app.state.started_at = datetime.now(timezone.utc).isoformat()

    # Hard-disable ChromaDB telemetry (PostHog) before any client is created.
    # The config off-switch is broken in chromadb 0.5.x, so neutralize directly.
    _silence_chromadb_telemetry()

    # Load and validate provider configuration
    # Clear cache first to ensure we pick up env vars set by CLI
    clear_settings_cache()
    strict_mode = settings.BRAINPALACE_STRICT_MODE

    try:
        provider_settings = load_provider_settings()
        # Reranking gate: the ENABLE_RERANKING env var (when set) wins; otherwise
        # the per-project ``reranker.enabled`` config drives it (default ON). The
        # query path reads ``settings.ENABLE_RERANKING``, so reconcile it here so
        # config.yaml / `brainpalace init` can turn reranking on/off.
        if os.getenv("ENABLE_RERANKING") is None:
            try:
                settings.ENABLE_RERANKING = bool(
                    getattr(provider_settings.reranker, "enabled", True)
                )
            except Exception:  # noqa: BLE001 — never block startup on this
                pass
        enable_reranking = getattr(settings, "ENABLE_RERANKING", False)
        validation_errors = validate_provider_config(
            provider_settings,
            reranking_enabled=bool(enable_reranking),
        )

        if validation_errors:
            for error in validation_errors:
                if error.severity == ValidationSeverity.CRITICAL:
                    logger.error(f"Provider config error: {error}")
                else:
                    logger.warning(f"Provider config warning: {error}")

            # In strict mode, fail on critical errors
            if strict_mode and has_critical_errors(validation_errors):
                critical_msgs = [
                    str(e)
                    for e in validation_errors
                    if e.severity == ValidationSeverity.CRITICAL
                ]
                raise RuntimeError(
                    f"Critical provider configuration errors (strict mode): "
                    f"{'; '.join(critical_msgs)}"
                )

        # Log active provider configuration
        logger.info(
            f"Embedding provider: {provider_settings.embedding.provider} "
            f"(model: {provider_settings.embedding.model})"
        )
        logger.info(
            f"Summarization provider: {provider_settings.summarization.provider} "
            f"(model: {provider_settings.summarization.model})"
        )

        # Phase G: apply graphrag: YAML config onto GRAPH_* settings.
        # Env vars win — this only fills settings the environment didn't set.
        _apply_graphrag_yaml_overrides(provider_settings)
    except Exception as e:
        logger.error(f"Failed to load provider configuration: {e}")
        # Continue with defaults - EmbeddingGenerator will handle provider creation

    if settings.OPENAI_API_KEY:
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    # Determine mode and resolve paths
    mode = settings.BRAINPALACE_MODE
    state_dir = _state_dir  # May be set by run() function

    # If not set via run(), check environment variable (set by CLI subprocess)
    if state_dir is None and settings.BRAINPALACE_STATE_DIR:
        state_dir = Path(settings.BRAINPALACE_STATE_DIR).resolve()
        logger.info(f"Using state directory from environment: {state_dir}")

    storage_paths: dict[str, Path] | None = None

    if state_dir is not None:
        # Per-project mode with explicit state directory
        mode = "project"

        # Check for stale locks and clean up
        if is_stale(state_dir):
            logger.info(f"Cleaning stale lock in {state_dir}")
            cleanup_stale(state_dir)

        # Acquire exclusive lock
        if not acquire_lock(state_dir):
            raise RuntimeError(
                f"Another BrainPalace instance is already running for {state_dir}"
            )

        # Resolve storage paths (creates directories)
        storage_paths = resolve_storage_paths(state_dir)
        logger.info(f"State directory: {state_dir}")
    elif state_dir is None:
        # Fallback for direct server runs with no explicit state directory.
        # Resolve relative to project root to avoid CWD-relative storage paths.
        try:
            state_dir = resolve_state_dir(Path.cwd())
            storage_paths = resolve_storage_paths(state_dir)
            logger.info(f"Resolved fallback state directory: {state_dir}")
        except Exception as e:
            logger.warning(f"Failed to resolve fallback storage paths: {e}")
            # Guaranteed fallback: use .brainpalace in CWD so state_dir is never None
            state_dir = Path.cwd() / ".brainpalace"
            state_dir.mkdir(parents=True, exist_ok=True)
            storage_paths = resolve_storage_paths(state_dir)
            logger.info(f"Created fallback state directory: {state_dir}")

    # At this point state_dir is guaranteed non-None
    assert state_dir is not None, "state_dir must be resolved by lifespan"
    logger.info(f"Resolved storage paths: state_dir={state_dir}")

    # File logging to <state_dir>/server.log so the dashboard /health/logs tail
    # has something to read (the base config only logs to the console). Small
    # rotating handler (1MB x 3); attach once and remember the path on state.
    app.state.log_file_path = None
    try:
        from logging.handlers import RotatingFileHandler

        log_path = state_dir / "server.log"
        root_logger = logging.getLogger()
        already = any(
            isinstance(h, RotatingFileHandler) and getattr(h, "_brainpalace_log", False)
            for h in root_logger.handlers
        )
        if not already:
            file_handler = RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            file_handler._brainpalace_log = True  # type: ignore[attr-defined]
            root_logger.addHandler(file_handler)
        app.state.log_file_path = str(log_path)
        logger.info("Server log file: %s", log_path)
    except Exception as exc:  # noqa: BLE001 — never block startup on log file
        logger.warning("Could not set up server log file: %s", exc)

    # Phase M: pin GRAPH_INDEX_PATH to the project-resolved path before any
    # code triggers GraphStoreManager.get_instance(). Phase I covered the
    # vector store + BM25 manager via explicit constructors, but the graph
    # store still defaulted to settings.GRAPH_INDEX_PATH ("./graph_index"),
    # which is CWD-relative — landing graph data at whatever directory the
    # `brainpalace start` CLI was invoked from rather than under
    # <project>/.brainpalace/data/graph_index/.
    #
    # Precedence: env var > YAML graphrag.index_path > Phase M pin > default.
    # Skip the pin if either an env var or YAML already set a non-default
    # value (both ran before this point).
    _graph_path_default = "./graph_index"
    if (
        storage_paths
        and "graph_index" in storage_paths
        and "GRAPH_INDEX_PATH" not in os.environ
        and settings.GRAPH_INDEX_PATH == _graph_path_default
    ):
        settings.GRAPH_INDEX_PATH = str(storage_paths["graph_index"])
        logger.info(
            f"GRAPH_INDEX_PATH pinned to project state dir: "
            f"{settings.GRAPH_INDEX_PATH}"
        )

    # Determine project root for path validation
    project_root: Path | None = None
    if state_dir is not None:
        # Project root is parent of .brainpalace (depth 1)
        # or 3 levels up from legacy .claude/brainpalace (depth 3)
        from brainpalace_server.storage_paths import LEGACY_STATE_DIR_NAME

        if state_dir.name == ".brainpalace":
            project_root = state_dir.parent
        elif str(state_dir).endswith(LEGACY_STATE_DIR_NAME):
            project_root = state_dir.parent.parent.parent
        else:
            # Custom state dir — use env var or resolve
            env_root = os.environ.get("BRAINPALACE_PROJECT_ROOT")
            if env_root:
                project_root = Path(env_root).resolve()
            else:
                project_root = resolve_project_root(state_dir)

    # Expose project root for the /runtime/ endpoint (B8).
    app.state.project_root = str(project_root) if project_root else ""

    # Phase H: Build the .gitignore matcher once per project_root.
    gitignore_matcher = None
    if (
        settings.BRAINPALACE_HONOR_GITIGNORE
        and project_root is not None
        and project_root.is_dir()
    ):
        from brainpalace_server.indexing.gitignore_matcher import GitignoreMatcher

        try:
            gitignore_matcher = GitignoreMatcher.from_project_root(project_root)
            logger.info(
                f"Loaded gitignore matcher: "
                f"{len(gitignore_matcher._specs_by_dir)} .gitignore file(s) "
                f"under {project_root}"
            )
        except Exception as exc:
            logger.warning(
                f"Failed to build GitignoreMatcher for {project_root}: {exc} "
                "— continuing without .gitignore awareness"
            )
            gitignore_matcher = None

    try:
        # Initialize storage backend (Phase 5)
        backend_type = get_effective_backend_type()
        logger.info(f"Storage backend: {backend_type}")

        # Phase I: For the chroma backend, build the vector store + BM25
        # managers with the project-resolved persist dirs and register them
        # as the module singletons BEFORE get_storage_backend() runs — so the
        # ChromaBackend's get_vector_store()/get_bm25_manager() fallback
        # reuses these instead of constructing CWD-relative ones.
        vector_store = None
        bm25_manager = None
        if backend_type == "chroma":
            # Determine persistence directories
            if storage_paths:
                chroma_dir = str(storage_paths["chroma_db"])
                bm25_dir = str(storage_paths["bm25_index"])
            elif state_dir is not None:
                chroma_dir = str(state_dir / "data" / "chroma_db")
                bm25_dir = str(state_dir / "data" / "bm25_index")
            else:
                # Unreachable: state_dir is always resolved above.
                raise RuntimeError(
                    "Storage path resolution failed: state_dir is unexpectedly None"
                )

            # Initialize ChromaDB components
            vector_store = VectorStoreManager(
                persist_dir=chroma_dir,
            )
            await vector_store.initialize()
            set_vector_store(vector_store)
            app.state.vector_store = vector_store
            logger.info(f"Vector store initialized: {chroma_dir}")

            # Self-heal a corrupt on-disk HNSW index BEFORE any write. A store
            # left inconsistent by a past duplicate-server write or an
            # interrupted upsert segfaults the process on the next upsert (native
            # HNSW resize, no traceback), so the server crash-loops on every
            # start. Rebuild it from ChromaDB's intact SQLite — no re-embedding —
            # so startup indexing can't trip the corruption.
            try:
                recovered = await vector_store.heal_if_corrupt()
                if recovered:
                    logger.warning(
                        "Vector index self-heal rebuilt %d vectors", recovered
                    )
            except Exception as exc:  # noqa: BLE001 — heal must never block startup
                logger.warning("Vector index self-heal check failed: %s", exc)

            # Check embedding compatibility (PROV-07)
            embedding_warning = await check_embedding_compatibility(vector_store)
            if embedding_warning:
                logger.warning(f"Embedding compatibility: {embedding_warning}")
                # Store warning for health endpoint
                app.state.embedding_warning = embedding_warning
            else:
                app.state.embedding_warning = None

            _bm = load_bm25_config()
            bm25_manager = BM25IndexManager(
                persist_dir=bm25_dir,
                default_lang=_bm.language,
                engine=_bm.engine,
            )
            bm25_manager.initialize()
            set_bm25_manager(bm25_manager)
            app.state.bm25_manager = bm25_manager
            logger.info(f"BM25 index manager initialized: {bm25_dir}")
        else:
            # PostgreSQL or other backend - no ChromaDB components needed
            app.state.vector_store = None
            app.state.bm25_manager = None
            app.state.embedding_warning = None
            logger.info(f"Skipping ChromaDB initialization (backend: {backend_type})")

        # Get storage backend instance from factory. For chroma this now
        # picks up the singletons registered above (correct persist dirs).
        storage_backend = get_storage_backend()
        await storage_backend.initialize()
        app.state.storage_backend = storage_backend
        app.state.backend_type = backend_type
        logger.info("Storage backend initialized")

        # Initialize embedding cache service (Phase 16)
        # Must be initialized BEFORE IndexingService so get_embedding_cache()
        # returns the instance when the first embed call happens.
        from brainpalace_server.services.embedding_cache import (
            EmbeddingCacheService,
            set_embedding_cache,
        )

        if storage_paths:
            cache_db_path = storage_paths["embedding_cache"] / "embeddings.db"
        elif state_dir is not None:
            cache_db_path = state_dir / "embedding_cache" / "embeddings.db"
            cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            import tempfile

            cache_db_path = (
                Path(tempfile.mkdtemp(prefix="brainpalace-cache-")) / "embeddings.db"
            )

        provider_fingerprint = _build_provider_fingerprint()
        embedding_cache = EmbeddingCacheService(
            db_path=cache_db_path,
            max_mem_entries=settings.EMBEDDING_CACHE_MAX_MEM_ENTRIES,
            max_disk_mb=settings.EMBEDDING_CACHE_MAX_DISK_MB,
            persist_stats=settings.EMBEDDING_CACHE_PERSIST_STATS,
        )
        await embedding_cache.initialize(provider_fingerprint)
        set_embedding_cache(embedding_cache)
        app.state.embedding_cache = embedding_cache
        logger.info("Embedding cache service initialized")

        # Initialize query cache (Phase 17)
        from brainpalace_server.services.query_cache import (
            QueryCacheService,
            set_query_cache,
        )

        query_cache = QueryCacheService(
            ttl=settings.QUERY_CACHE_TTL,
            max_size=settings.QUERY_CACHE_MAX_SIZE,
        )
        set_query_cache(query_cache)
        app.state.query_cache = query_cache
        logger.info(
            "Query cache initialized (TTL=%ds, max_size=%d)",
            settings.QUERY_CACHE_TTL,
            settings.QUERY_CACHE_MAX_SIZE,
        )

        # Load project config for exclude patterns
        exclude_patterns = None
        if state_dir:
            from brainpalace_server.config.settings import load_project_config

            project_config = load_project_config(state_dir)
            exclude_patterns = project_config.get("exclude_patterns")
            if exclude_patterns:
                logger.info(
                    f"Using exclude patterns from config: {exclude_patterns[:3]}..."
                )

        # Initialize FolderManager for indexed folder tracking (Phase 12)
        if state_dir is not None:
            folder_manager_dir = state_dir
        else:
            # No state directory — use a temp dir (in-memory equivalent)
            import tempfile

            folder_manager_dir = Path(tempfile.mkdtemp(prefix="brainpalace-folders-"))
        folder_manager = FolderManager(state_dir=folder_manager_dir)
        await folder_manager.initialize()
        app.state.folder_manager = folder_manager
        logger.info("Folder manager initialized")

        # Create document loader with exclude patterns
        from brainpalace_server.indexing import DocumentLoader

        document_loader = DocumentLoader(
            exclude_patterns=exclude_patterns,
            gitignore_matcher=gitignore_matcher,
        )

        # Initialize ManifestTracker for incremental indexing (Phase 14)
        manifest_tracker = None
        if storage_paths and "manifests" in storage_paths:
            from brainpalace_server.services.manifest_tracker import ManifestTracker

            manifest_tracker = ManifestTracker(manifests_dir=storage_paths["manifests"])
            logger.info("Manifest tracker initialized")
        elif state_dir is not None:
            from brainpalace_server.services.manifest_tracker import ManifestTracker

            manifest_tracker = ManifestTracker(manifests_dir=state_dir / "manifests")
            logger.info("Manifest tracker initialized (fallback)")

        # Create indexing service with storage_backend (Phase 9)
        indexing_service = IndexingService(
            storage_backend=storage_backend,
            document_loader=document_loader,
            folder_manager=folder_manager,
            manifest_tracker=manifest_tracker,
        )
        app.state.indexing_service = indexing_service

        # Self-heal manifest/store drift on every start (e.g. inflated folder
        # counts + store orphans left by a past duplicate-server incident).
        # No reindex, no re-embed: pure bookkeeping + targeted deletes; a no-op
        # when consistent. Never block startup on it.
        try:
            from brainpalace_server.services.startup_reconcile import (
                reconcile_folders,
            )

            await reconcile_folders(folder_manager, manifest_tracker, storage_backend)
        except Exception as exc:  # noqa: BLE001 — heal must never block startup
            logger.warning("Startup reconcile failed (non-fatal): %s", exc)

        # Curated memory namespace (Phase 030). Markdown source-of-truth +
        # a dedicated Chroma collection as a rebuildable shadow index.
        memory_service = None
        if getattr(settings, "MEMORY_ENABLED", True):
            from brainpalace_server.indexing import get_embedding_generator
            from brainpalace_server.services import MemoryService

            if settings.MEMORY_PATH:
                mem_path = settings.MEMORY_PATH
            elif app.state.project_root:
                mem_path = str(Path(app.state.project_root) / "BRAINPALACE_MEMORY.md")
            else:
                mem_path = str(state_dir / "BRAINPALACE_MEMORY.md")

            mem_vector_store = None
            base_vs = getattr(app.state, "vector_store", None)
            if base_vs is not None and getattr(base_vs, "persist_dir", None):
                mem_vector_store = VectorStoreManager(
                    persist_dir=base_vs.persist_dir,
                    collection_name=settings.MEMORY_COLLECTION,
                )
                await mem_vector_store.initialize()
                # Same HNSW-corruption self-heal as the code collection.
                try:
                    healed = await mem_vector_store.heal_if_corrupt()
                    if healed:
                        logger.warning(
                            "Memory vector index self-heal rebuilt %d vectors",
                            healed,
                        )
                except Exception as exc:  # noqa: BLE001 — never block startup
                    logger.warning("Memory index self-heal check failed: %s", exc)

            memory_service = MemoryService(
                path=mem_path,
                vector_store=mem_vector_store,
                embedding_generator=get_embedding_generator(),
            )
            app.state.memory_service = memory_service
            logger.info("Memory namespace initialized: %s", mem_path)

            # Self-heal (ADR 0001): if the shadow index is empty but the
            # markdown has entries (e.g. .brainpalace/ was wiped), rebuild it.
            if mem_vector_store is not None:
                try:
                    empty = await mem_vector_store.get_count() == 0
                    if empty and memory_service.load():
                        n = await memory_service.rebuild_from_markdown()
                        logger.info("Rebuilt memory index from markdown: %d", n)
                except Exception as exc:  # noqa: BLE001 — never block startup
                    logger.warning("Memory index rebuild check failed: %s", exc)
        else:
            app.state.memory_service = None

        # Session-start context assembler (Phase 035)
        if getattr(settings, "CONTEXT_ENABLED", True):
            from brainpalace_server.services import SessionContextService

            app.state.session_context_service = SessionContextService(
                memory_service=memory_service,
            )
        else:
            app.state.session_context_service = None

        # Session archive + indexing (Phase 050) — two INDEPENDENT capabilities.
        #   archive: copy raw transcripts (durable backup, no embeddings). ON by
        #     default incl. existing projects (absent block). SESSION_ARCHIVE_ENABLED.
        #   index: embed archived transcripts (billable opt-in). ON only when the
        #     session_indexing block is present. SESSION_INDEXING_ENABLED.
        # Never blocks startup.
        app.state.session_index_service = None
        app.state.session_indexing_config = None
        app.state.session_reconciler = None
        app.state.session_distiller = None
        app.state.session_archive_service = None
        app.state.session_archive_watcher = None
        app.state.session_archive_enabled = False
        app.state.session_index_enabled = False
        try:
            from brainpalace_server.config.session_config import (
                load_session_indexing_config,
                resolve_session_capabilities,
            )

            session_cfg = load_session_indexing_config()
            app.state.session_indexing_config = session_cfg
            caps = resolve_session_capabilities(session_cfg)
            app.state.session_archive_enabled = caps.archive_enabled
            app.state.session_index_enabled = caps.index_enabled

            if (caps.archive_enabled or caps.index_enabled) and app.state.project_root:
                from brainpalace_server.services.session_index_service import (
                    encode_project_to_sessions_dir,
                )

                sessions_dir = (
                    Path(session_cfg.sessions_dir)
                    if session_cfg.sessions_dir
                    else encode_project_to_sessions_dir(app.state.project_root)
                )

                # Archive service — independent of indexing.
                archive_service = None
                if caps.archive_enabled:
                    from brainpalace_server.services.session_archive_service import (
                        SessionArchiveService,
                    )

                    arch_dir = Path(session_cfg.archive.dir)
                    if not arch_dir.is_absolute():
                        arch_dir = Path(app.state.project_root) / arch_dir
                    archive_service = SessionArchiveService(
                        archive_dir=arch_dir, tool=caps.tool
                    )
                app.state.session_archive_service = archive_service

                # Index service — only when indexing is enabled.
                sess_svc = None
                if caps.index_enabled:
                    from brainpalace_server.indexing import get_embedding_generator
                    from brainpalace_server.services.session_index_service import (
                        SessionIndexService,
                    )

                    sess_svc = SessionIndexService(
                        embedding_generator=get_embedding_generator(),
                        storage_backend=storage_backend,
                    )
                app.state.session_index_service = sess_svc

                # Phase 080: provider-engine distiller — the (billable) server-side
                # summarizer. Built ONLY when mode in (provider, auto) AND
                # SESSION_DISTILL_ENABLED is truthy (disabled by default), so its
                # presence is the single gate every distill path checks. With the
                # default mode=subagent or the default-off switch it stays None →
                # no server-side summarization ever runs. Works even when index is
                # OFF (needs only storage_backend + embedder + summarizer). Never
                # blocks startup; failure leaves distiller=None (archive still runs).
                distiller = None
                try:
                    from brainpalace_server.config.session_config import (
                        load_session_extraction_config,
                        session_distill_enabled,
                        session_distill_grace_hours,
                    )

                    extract_cfg = load_session_extraction_config()
                    extract_mode = extract_cfg.mode
                    if (
                        extract_mode in ("provider", "auto")
                        and session_distill_enabled()
                        and app.state.project_root
                    ):
                        from brainpalace_server.indexing import (
                            get_embedding_generator,
                        )
                        from brainpalace_server.providers.factory import (
                            ProviderRegistry,
                        )
                        from brainpalace_server.services import (
                            session_distill_service as _distill,
                        )
                        from brainpalace_server.services.plugin_detect import (
                            claude_plugin_installed,
                        )

                        distill_graph = None
                        if getattr(settings, "ENABLE_GRAPH_INDEX", False):
                            from brainpalace_server.storage.graph_store import (
                                get_graph_store_manager,
                            )

                            distill_graph = get_graph_store_manager()
                        _proj = app.state.project_root
                        distiller = _distill.SessionDistiller(
                            summarizer=ProviderRegistry.get_summarization_provider(
                                load_provider_settings().summarization
                            ),
                            embedder=get_embedding_generator(),
                            storage_backend=storage_backend,
                            project_root=_proj,
                            graph_store=distill_graph,
                            memory_service=app.state.memory_service,
                            digest_path=str(Path(_proj) / "BRAINPALACE_DECISIONS.md"),
                            mode=extract_mode,
                            idle_seconds=extract_cfg.quiescence_seconds,
                            plugin_present=lambda: claude_plugin_installed(
                                project=Path(_proj)
                            ),
                            grace_hours=session_distill_grace_hours(),
                        )
                        app.state.session_distiller = distiller
                        logger.info(
                            "Session distiller enabled (engine=%s).", extract_mode
                        )
                except Exception as exc:  # noqa: BLE001 — never block startup
                    logger.warning("Session distiller setup failed: %s", exc)

                # Periodic reconcile: archives always, indexes only when enabled.
                # The first tick runs immediately (the boot sweep — sync + index +
                # distiller catch-up); thereafter copy cadence is
                # session_archive.reconcile_seconds. Per-event copy is retired, so a
                # growing session is re-copied at most once per interval (the final
                # tail is captured on the first sweep after it goes quiet).
                if archive_service is not None or sess_svc is not None:
                    from brainpalace_server.services.session_reconciler import (
                        SessionReconciler,
                    )

                    reconciler = SessionReconciler(
                        interval_seconds=session_cfg.archive.reconcile_seconds,
                        sessions_dir=sessions_dir,
                        archive_service=archive_service,
                        sess_svc=sess_svc,
                        session_cfg=session_cfg,
                        caps=caps,
                        distiller=distiller,
                    )
                    await reconciler.start()
                    app.state.session_reconciler = reconciler

                # Archive deletion watcher — purges chunks only when indexing.
                if archive_service is not None:
                    from brainpalace_server.services.session_archive_watcher import (
                        SessionArchiveWatcher,
                    )

                    archive_watcher = SessionArchiveWatcher(
                        archive_service.archive_dir,
                        archive_service,
                        storage_backend if caps.index_enabled else None,
                        purge_index=caps.index_enabled,
                    )
                    await archive_watcher.start()
                    app.state.session_archive_watcher = archive_watcher
                logger.info(
                    "Session capabilities — archive=%s index=%s (%s)",
                    caps.archive_enabled,
                    caps.index_enabled,
                    sessions_dir,
                )
        except Exception as exc:  # noqa: BLE001 — never block startup on sessions
            logger.warning("Session archive/index setup failed: %s", exc)

        # Git-history indexing (Phase 130) — opt-in commit ingest. OFF unless
        # the project sets git_indexing.enabled and the env kill-switch
        # (GIT_INDEXING_ENABLED) isn't false. Never blocks startup.
        app.state.git_index_service = None
        app.state.git_indexing_config = None
        try:
            from brainpalace_server.config.git_config import (
                load_git_indexing_config,
            )

            git_cfg = load_git_indexing_config()
            app.state.git_indexing_config = git_cfg
            if git_cfg.enabled and app.state.project_root:
                from brainpalace_server.indexing import get_embedding_generator
                from brainpalace_server.services.git_history_index_service import (
                    GitHistoryIndexService,
                )

                git_svc = GitHistoryIndexService(
                    embedding_generator=get_embedding_generator(),
                    storage_backend=storage_backend,
                    state_dir=state_dir,
                )
                app.state.git_index_service = git_svc

                async def _boot_git_index() -> None:
                    try:
                        summary = await git_svc.index_repo(
                            app.state.project_root, git_cfg
                        )
                        logger.info(
                            "Git boot-index: %d new commit(s)",
                            summary.get("commits_new", 0),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Git boot-index failed: %s", exc)

                asyncio.create_task(_boot_git_index())
                logger.info("Git indexing enabled: %s", app.state.project_root)
        except Exception as exc:  # noqa: BLE001 — never block startup on git
            logger.warning("Git indexing setup failed: %s", exc)

        # Create query service with storage_backend (Phase 9)
        query_service = QueryService(
            storage_backend=storage_backend,
            query_cache=query_cache,
            memory_service=memory_service,
        )
        app.state.query_service = query_service

        # Query history log (dashboard "Queries" tab). ON by default with a
        # 7-day retention; QUERY_LOG_ENABLED=false hard-disables. Writes are
        # fire-and-forget from the /query/ endpoint. Never blocks startup.
        app.state.query_log_service = None
        try:
            from brainpalace_server.config.query_log_config import (
                load_query_log_config,
            )
            from brainpalace_server.services.query_log import QueryLogService

            ql_cfg = load_query_log_config()
            if ql_cfg.enabled and state_dir is not None:
                query_log_service = QueryLogService(
                    state_dir / "query_log.db",
                    enabled=True,
                    retention_days=ql_cfg.retention_days,
                )
                purged = query_log_service.purge(ql_cfg.retention_days)
                app.state.query_log_service = query_log_service
                logger.info(
                    "Query log enabled (retention_days=%d, purged=%d)",
                    ql_cfg.retention_days,
                    purged,
                )
            else:
                logger.info("Query log disabled")
        except Exception as exc:  # noqa: BLE001 — never block startup on query log
            logger.warning("Query log setup failed: %s", exc)

        # Initialize job queue system (Feature 115)
        if state_dir is not None:
            # Initialize job queue store
            job_store = JobQueueStore(state_dir)
            stale_jobs = await job_store.initialize()
            logger.info("Job queue store initialized")

            # Initialize job queue service
            job_service = JobQueueService(
                store=job_store,
                project_root=project_root,
            )
            app.state.job_service = job_service
            logger.info("Job queue service initialized")

            # D14 — auto-reindex affected folders after stuck-job recovery.
            # select_reenqueue_candidates dedupes by folder_path and excludes
            # permanently-FAILED jobs (retry budget exhausted) so a job that
            # deterministically crashes the server is not re-enqueued into an
            # infinite loop; the C1 dedupe path handles overlap with any active
            # PENDING/RUNNING jobs.
            for stale in select_reenqueue_candidates(stale_jobs):
                try:
                    resp = await job_service.reenqueue_from_record(stale)
                    logger.info(
                        "Re-enqueued reindex after stale-job recovery: "
                        f"folder={stale.folder_path} job_id={resp.job_id} "
                        f"dedupe_hit={resp.dedupe_hit}"
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to re-enqueue reindex for "
                        f"{stale.folder_path}: {exc}"
                    )

            # Initialize and start job worker
            _job_worker = JobWorker(
                job_store=job_store,
                indexing_service=indexing_service,
                max_runtime_seconds=settings.BRAINPALACE_JOB_TIMEOUT,
                progress_checkpoint_interval=settings.BRAINPALACE_CHECKPOINT_INTERVAL,
            )
            await _job_worker.start()
            logger.info("Job worker started")

            # Initialize and start file watcher service (Phase 15)
            from brainpalace_server.services.file_watcher_service import (
                FileWatcherService,
            )

            _file_watcher = FileWatcherService(
                folder_manager=folder_manager,
                job_service=job_service,
                default_debounce_seconds=settings.BRAINPALACE_WATCH_DEBOUNCE_SECONDS,
                post_enqueue_cooldown_seconds=(
                    settings.BRAINPALACE_WATCH_POST_ENQUEUE_COOLDOWN_SECONDS
                ),
                gitignore_matcher=gitignore_matcher,
            )
            await _file_watcher.start()
            app.state.file_watcher_service = _file_watcher
            logger.info("File watcher service started")

            # Wire JobWorker to FileWatcherService and FolderManager (Phase 15-02)
            _job_worker.set_file_watcher_service(_file_watcher)
            _job_worker.set_folder_manager(folder_manager)
            # Wire JobWorker to QueryCacheService (Phase 17)
            _job_worker.set_query_cache(query_cache)
        else:
            # No state directory - create minimal job service for backward compat
            # Jobs will not be persisted in this mode
            logger.warning(
                "No state directory configured - job queue persistence disabled"
            )
            # Create in-memory store with temp directory
            import tempfile

            temp_dir = Path(tempfile.mkdtemp(prefix="brainpalace-"))
            job_store = JobQueueStore(temp_dir)
            stale_jobs = await job_store.initialize()

            job_service = JobQueueService(
                store=job_store,
                project_root=project_root,
            )
            app.state.job_service = job_service

            # D14 — see state-dir branch above.
            for stale in select_reenqueue_candidates(stale_jobs):
                try:
                    resp = await job_service.reenqueue_from_record(stale)
                    logger.info(
                        "Re-enqueued reindex after stale-job recovery: "
                        f"folder={stale.folder_path} job_id={resp.job_id} "
                        f"dedupe_hit={resp.dedupe_hit}"
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to re-enqueue reindex for "
                        f"{stale.folder_path}: {exc}"
                    )

            _job_worker = JobWorker(
                job_store=job_store,
                indexing_service=indexing_service,
                max_runtime_seconds=settings.BRAINPALACE_JOB_TIMEOUT,
                progress_checkpoint_interval=settings.BRAINPALACE_CHECKPOINT_INTERVAL,
            )
            await _job_worker.start()

            # Initialize and start file watcher service (Phase 15, no-state-dir branch)
            from brainpalace_server.services.file_watcher_service import (
                FileWatcherService,
            )

            _file_watcher = FileWatcherService(
                folder_manager=folder_manager,
                job_service=job_service,
                default_debounce_seconds=settings.BRAINPALACE_WATCH_DEBOUNCE_SECONDS,
                post_enqueue_cooldown_seconds=(
                    settings.BRAINPALACE_WATCH_POST_ENQUEUE_COOLDOWN_SECONDS
                ),
                gitignore_matcher=gitignore_matcher,
            )
            await _file_watcher.start()
            app.state.file_watcher_service = _file_watcher

            # Wire JobWorker to FileWatcherService and FolderManager (Phase 15-02)
            _job_worker.set_file_watcher_service(_file_watcher)
            _job_worker.set_folder_manager(folder_manager)
            # Wire JobWorker to QueryCacheService (Phase 17)
            _job_worker.set_query_cache(query_cache)

        # Set multi-instance metadata on app.state for health endpoint
        app.state.mode = mode
        app.state.instance_id = _runtime_state.instance_id if _runtime_state else None
        app.state.project_id = _runtime_state.project_id if _runtime_state else None
        app.state.active_projects = None  # For shared mode (future)
        app.state.strict_mode = strict_mode

    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        # Clean up lock if we acquired it
        if state_dir is not None:
            release_lock(state_dir)
        raise

    yield

    logger.info("Shutting down BrainPalace RAG server...")

    # Stop file watcher service BEFORE job worker (Phase 15)
    if _file_watcher is not None:
        from brainpalace_server.services.file_watcher_service import FileWatcherService

        if isinstance(_file_watcher, FileWatcherService):
            await _file_watcher.stop()
            logger.info("File watcher service stopped")

    # Stop session reconciler (periodic archive copy/index sweep)
    session_reconciler = getattr(app.state, "session_reconciler", None)
    if session_reconciler is not None:
        try:
            await session_reconciler.stop()
            logger.info("Session reconciler stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session reconciler stop failed: %s", exc)
        _file_watcher = None

    archive_watcher_shutdown = getattr(app.state, "session_archive_watcher", None)
    if archive_watcher_shutdown is not None:
        try:
            await archive_watcher_shutdown.stop()
            logger.info("Session archive watcher stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session archive watcher stop failed: %s", exc)

    # Stop job worker gracefully
    if _job_worker is not None:
        await _job_worker.stop()
        logger.info("Job worker stopped")
        _job_worker = None

    # Reset query cache singleton (Phase 17)
    from brainpalace_server.services.query_cache import reset_query_cache

    reset_query_cache()

    # Close storage backend if it has a close method (PostgreSQL pool)
    shutdown_backend = getattr(app.state, "storage_backend", None)
    if shutdown_backend is not None and hasattr(shutdown_backend, "close"):
        await shutdown_backend.close()
        logger.info("Storage backend connection pool closed")

    # Cleanup for per-project mode
    if state_dir is not None:
        delete_runtime(state_dir)
        release_lock(state_dir)
        logger.info(f"Released lock and cleaned up state in {state_dir}")


# Create FastAPI application
app = FastAPI(
    title="BrainPalace RAG API",
    description=(
        "RAG-based document indexing and semantic search API. "
        "Index documents from folders and query them using natural language."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(index_router, prefix="/index", tags=["Indexing"])
app.include_router(cache_router, prefix="/index/cache", tags=["Cache"])
app.include_router(folders_router, prefix="/index/folders", tags=["Folders"])
app.include_router(jobs_router, prefix="/index/jobs", tags=["Jobs"])
app.include_router(query_router, prefix="/query", tags=["Querying"])
app.include_router(runtime_router, prefix="/runtime", tags=["Runtime"])
from brainpalace_server.api.routers.memories import (  # noqa: E402 — late import, registered after app setup
    router as memories_router,
)

app.include_router(memories_router, prefix="/memories", tags=["Memory"])
from brainpalace_server.api.routers.context import (  # noqa: E402 — late import, registered after app setup
    router as context_router,
)

app.include_router(context_router, prefix="/context", tags=["Context"])
from brainpalace_server.api.routers.sessions import (  # noqa: E402 — late import, registered after app setup
    router as sessions_router,
)

app.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])
from brainpalace_server.api.routers.git import (  # noqa: E402 — late import, registered after app setup
    router as git_router,
)

app.include_router(git_router, prefix="/git", tags=["Git"])


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Root endpoint redirects to docs."""
    return {
        "name": "BrainPalace RAG API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


def _find_free_port() -> int:
    """Find a free port by binding to port 0.

    Returns:
        An available port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port  # type: ignore[no-any-return]


def run(
    host: str | None = None,
    port: int | None = None,
    reload: bool | None = None,
    state_dir: str | None = None,
) -> None:
    """Run the server using uvicorn.

    Args:
        host: Host to bind to (default: from settings)
        port: Port to bind to (default: from settings, 0 = auto-assign)
        reload: Enable auto-reload (default: from DEBUG setting)
        state_dir: State directory for per-project mode (enables locking)
    """
    global _runtime_state, _state_dir

    resolved_host = host or settings.API_HOST
    resolved_port = port if port is not None else settings.API_PORT

    # Handle port 0: find a free port
    if resolved_port == 0:
        resolved_port = _find_free_port()
        logger.info(f"Auto-assigned port: {resolved_port}")

    # Set up per-project mode if state_dir specified
    if state_dir:
        _state_dir = Path(state_dir).resolve()

        # Determine project root from state dir layout
        if _state_dir.name == ".brainpalace":
            _project_root = str(_state_dir.parent)
        else:
            # Legacy .claude/brainpalace or custom path
            env_root = os.environ.get("BRAINPALACE_PROJECT_ROOT")
            _project_root = env_root or str(_state_dir.parent.parent.parent)

        # Create runtime state
        _runtime_state = RuntimeState(
            mode="project",
            project_root=_project_root,
            bind_host=resolved_host,
            port=resolved_port,
            pid=os.getpid(),
            base_url=f"http://{resolved_host}:{resolved_port}",
        )

        # Write runtime.json before starting server
        # Note: Lock is acquired in lifespan, but we write runtime early
        # for port discovery by CLI tools
        _state_dir.mkdir(parents=True, exist_ok=True)
        write_runtime(_state_dir, _runtime_state)
        logger.info(f"Per-project mode enabled: {_state_dir}")

    uvicorn.run(
        "brainpalace_server.api.main:app",
        host=resolved_host,
        port=resolved_port,
        reload=reload if reload is not None else settings.DEBUG,
    )


@click.command()
@click.version_option(version=__version__, prog_name="brainpalace-serve")
@click.option(
    "--host",
    "-h",
    default=None,
    help=f"Host to bind to (default: {settings.API_HOST})",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=None,
    help=f"Port to bind to (default: {settings.API_PORT}, 0 = auto-assign)",
)
@click.option(
    "--reload/--no-reload",
    default=None,
    help=f"Enable auto-reload (default: {'enabled' if settings.DEBUG else 'disabled'})",
)
@click.option(
    "--state-dir",
    "-s",
    default=None,
    help="State directory for per-project mode (enables locking and runtime.json)",
)
@click.option(
    "--project-dir",
    "-d",
    default=None,
    help="Project directory (auto-resolves state-dir to .brainpalace)",
)
def cli(
    host: str | None,
    port: int | None,
    reload: bool | None,
    state_dir: str | None,
    project_dir: str | None,
) -> None:
    """BrainPalace RAG Server - Document indexing and semantic search API.

    Start the FastAPI server for document indexing and querying.

    \b
    Examples:
      brainpalace-serve                           # Start with default settings
      brainpalace-serve --port 8080               # Start on port 8080
      brainpalace-serve --port 0                  # Auto-assign an available port
      brainpalace-serve --host 0.0.0.0            # Bind to all interfaces
      brainpalace-serve --reload                  # Enable auto-reload
      brainpalace-serve --project-dir /my/project # Per-project mode
      brainpalace-serve --state-dir /path/.brainpalace          # Explicit state dir

    \b
    Environment Variables:
      API_HOST                Server host (default: 127.0.0.1)
      API_PORT                Server port (default: 8000)
      DEBUG                   Enable debug mode (default: false)
      BRAINPALACE_STATE_DIR   Override state directory
      BRAINPALACE_MODE        Instance mode: 'project' or 'shared'
    """
    # Resolve state directory from options
    resolved_state_dir = state_dir

    if project_dir and not state_dir:
        # Auto-resolve state-dir from project directory
        project_root = resolve_project_root(Path(project_dir))
        resolved_state_dir = str(resolve_state_dir(project_root))
    elif settings.BRAINPALACE_STATE_DIR and not state_dir:
        # Use environment variable if set
        resolved_state_dir = settings.BRAINPALACE_STATE_DIR

    run(host=host, port=port, reload=reload, state_dir=resolved_state_dir)


if __name__ == "__main__":
    cli()
