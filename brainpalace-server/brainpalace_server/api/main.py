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
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from brainpalace_server.config.runtime_mode import is_read_only
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
from brainpalace_server.runtime import RuntimeState, delete_runtime
from brainpalace_server.services import FolderManager, IndexingService, QueryService
from brainpalace_server.storage import (
    VectorStoreManager,
    get_effective_backend_type,
    get_storage_backend,
    set_vector_store,
)
from brainpalace_server.storage_paths import (
    db_path,
    resolve_state_dir,
    resolve_storage_paths,
    state_file_path,
)

from .routers import (
    cache_router,
    folders_router,
    health_router,
    index_router,
    ingest_router,
    jobs_router,
    query_router,
    records_router,
    rules_router,
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


def _probe_health(base_url: str, timeout: float = 3.0) -> dict[str, Any] | None:
    """GET ``<base_url>/health/`` and return the JSON body, or None.

    None on any non-200 / unreachable / unparseable response. Never raises.
    """
    import json
    import urllib.request

    try:
        req = urllib.request.Request(f"{base_url}/health/", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 — probe must never break startup
        return None


def _refuse_if_incumbent_alive(state_dir: Path) -> None:
    """Abort startup if another LIVE server already owns this project.

    The flock is the primary single-instance guard, but a stale-lock false
    positive (recycled pid, an unlinked lock file) historically let a SECOND
    server attach to the same ``.brainpalace/`` and corrupt the embedded,
    single-process ChromaDB. Before any stale-lock cleanup, probe the recorded
    server: if a *different*, healthy process answers ``/health`` **for this
    project**, raise instead of clearing the lock. Best-effort — an unreachable
    or unrelated endpoint lets a legitimate restart proceed.
    """
    try:
        from brainpalace_server.runtime import read_runtime

        state = read_runtime(state_dir)
    except Exception:  # noqa: BLE001 — never block startup on the probe
        return
    if state is None or not state.base_url:
        return
    # The CLI writes runtime.json with our own pid right after spawning us; that
    # record is not an incumbent.
    if state.pid and state.pid == os.getpid():
        return

    body = _probe_health(state.base_url)
    if body is None:
        return  # not answering — dead/stale; reclaim the lock normally below

    # A healthy server answered. Confirm it actually serves THIS project (guard
    # against an unrelated process that recycled the recorded port) before
    # refusing. If we can't tell, err toward refusing (safer than a duplicate).
    incumbent_root = str(body.get("project_root") or state.project_root or "")
    try:
        serves_this_project = bool(incumbent_root) and (
            Path(incumbent_root).resolve() == state_dir.parent.resolve()
        )
    except Exception:  # noqa: BLE001
        serves_this_project = bool(incumbent_root)
    if not serves_this_project:
        return

    raise RuntimeError(
        f"Another BrainPalace server (pid {state.pid}) is already live for this "
        f"project at {state.base_url}. Refusing to start a second server on the "
        f"same .brainpalace/ — two servers corrupt the embedded Chroma index. "
        f"Stop the running one first (`brainpalace stop`)."
    )


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


def _record_self_heal_result(report: dict[str, Any], persist_dir: str | None) -> None:
    """Notify + persist the startup self-heal outcome.

    Only acts when recovery actually engaged (a healthy no-op / count-precheck
    skip is silent). Emits a prominent startup log and appends an event that
    ``brainpalace status`` surfaces. Never raises.
    """
    rec = report.get("recovery")
    restored = int(getattr(rec, "restored", 0) or 0)
    recoverable = int(getattr(rec, "recoverable", 0) or 0)
    missed = int(getattr(rec, "missed", 0) or 0)
    residue = int(getattr(rec, "no_text", 0) or 0) + int(
        getattr(rec, "no_vector", 0) or 0
    )
    error = getattr(rec, "error", None)
    wanted = int(getattr(rec, "wanted", 0) or 0)
    files_dropped = int(report.get("files_dropped", 0) or 0)
    skipped = report.get("deep_clean_skipped_reason")

    if not (wanted or restored or files_dropped or error or skipped):
        return  # healthy no-op — nothing to report

    if error or skipped:
        logger.warning(
            "SELF-HEAL INCOMPLETE — restored=%d/%d, missed=%d, error=%s. Stage 2 "
            "(drop/clean/reindex) SKIPPED to protect data; fix and restart. "
            "(see `brainpalace status` → self_heal)",
            restored,
            recoverable,
            missed,
            error,
        )
    else:
        logger.warning(
            "SELF-HEAL: restored %d lost chunk(s) from cache+dead (no re-embed); "
            "marked %d not-fully-recovered file(s) pending verified reindex; "
            "%d chunk(s) need a source re-embed. "
            "(see `brainpalace status` → self_heal)",
            restored,
            files_dropped,
            residue,
        )

    if persist_dir:
        try:
            from brainpalace_server.services.chunk_recovery import (
                record_recovery_event,
            )

            record_recovery_event(
                persist_dir,
                {
                    "restored": restored,
                    "recoverable": recoverable,
                    "missed": missed,
                    "residue": residue,
                    "files_dropped": files_dropped,
                    "deep_clean_ran": bool(report.get("deep_clean_ran")),
                    "bm25_rebuilt": int(report.get("bm25_rebuilt", 0) or 0),
                    "incomplete_reason": skipped,
                    "error": error,
                },
            )
        except Exception as exc:  # noqa: BLE001 — persist must never block startup
            logger.warning("self-heal: persist failed: %s", exc)


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
        # provider is an (str, Enum); str() yields "EmbeddingProviderType.OPENAI",
        # but stored metadata holds the enum *value* ("openai"). Use .value so the
        # comparison/message don't false-positive a mismatch.
        _provider = provider_settings.embedding.provider
        current_provider = getattr(_provider, "value", str(_provider))
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


#: Marker recording which storage backend the project's index data lives under,
#: kept in the state dir (backend-independent — a switched-to backend is empty,
#: so we cannot read it from the store itself).
_INDEX_BACKEND_MARKER = ".index_backend"


def _read_index_backend_marker(state_dir: Path) -> str | None:
    try:
        p = state_file_path(state_dir, _INDEX_BACKEND_MARKER)
        return p.read_text(encoding="utf-8").strip() or None if p.is_file() else None
    except OSError:
        return None


def _write_index_backend_marker(state_dir: Path, backend: str) -> None:
    try:
        state_file_path(state_dir, _INDEX_BACKEND_MARKER).write_text(
            backend, encoding="utf-8"
        )
    except OSError as exc:  # best-effort — never block startup on the marker
        logger.warning("Could not write index-backend marker: %s", exc)


async def check_storage_backend_drift(
    state_dir: Path | None, backend_type: str, storage_backend: Any
) -> str | None:
    """Warn when the configured storage backend differs from the one the index
    was built under (a "db type" change that strands the existing index).

    Self-maintaining marker: whenever the CURRENT backend holds data we record it
    as the project's backend. If the current backend is empty but the marker
    names a DIFFERENT one, the data is stranded under that other store — warn.
    Returns None (no drift) for a fresh project or when data matches the marker.
    """
    if state_dir is None:
        return None
    try:
        count = (
            await storage_backend.get_count()
            if storage_backend is not None and storage_backend.is_initialized
            else 0
        )
    except Exception:  # noqa: BLE001 — diagnostic only, never raise on startup
        count = 0

    if count > 0:
        # Data is present under the configured backend — record it as the truth.
        if _read_index_backend_marker(state_dir) != backend_type:
            _write_index_backend_marker(state_dir, backend_type)
        return None

    prior = _read_index_backend_marker(state_dir)
    if prior and prior != backend_type:
        return (
            f"Storage backend changed: the index was built under '{prior}', but "
            f"config now uses '{backend_type}'. The existing index is not visible "
            f"under '{backend_type}' — switch the backend back, or re-index."
        )
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
        ("GRAPH_TRAVERSAL_DEPTH", "traversal_depth"),
        ("GRAPH_RRF_K", "rrf_k"),
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


def _apply_compute_yaml_overrides(provider_settings: "ProviderSettings") -> None:
    """Apply compute: YAML config to COMPUTE_MIN_CONFIDENCE — env vars win.

    Mirrors _apply_graphrag_yaml_overrides exactly. For each compute setting, if
    the corresponding environment variable is NOT set, and the compute: YAML
    section provided a value, copy the YAML value onto the module-level `settings`
    singleton. An explicit env var always takes precedence (12-factor).

    Must run before any code that reads these settings.
    """
    compute = provider_settings.compute
    for env_name, yaml_attr in (("COMPUTE_MIN_CONFIDENCE", "min_confidence"),):
        if os.environ.get(env_name) is not None:
            continue  # env-wins
        value = getattr(compute, yaml_attr, None)
        if value is not None:
            setattr(settings, env_name, value)


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
    # Task 4f: monotonic-ish wall clock for the auto-grace baseline (a restart
    # resets the provider grace window) + the cold-start gate (no auto-drain until
    # the first HTTP request arrives — set by the middleware below).
    app.state.server_start_ts = time.time()
    app.state.first_request_seen = False

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
        # the per-project ``reranker.enabled`` config drives it (default OFF). The
        # query path reads ``settings.ENABLE_RERANKING``, so reconcile it here so
        # config.yaml / `brainpalace init` can turn reranking on/off.
        if os.getenv("ENABLE_RERANKING") is None:
            try:
                settings.ENABLE_RERANKING = bool(
                    getattr(provider_settings.reranker, "enabled", False)
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
        # Phase 0: apply compute: YAML config onto compute settings.
        _apply_compute_yaml_overrides(provider_settings)
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

        # #1: never attach a second live server to one project's .brainpalace/.
        # Probe the recorded server BEFORE any stale-lock cleanup so an eager
        # "stale" verdict can't clear the lock out from under a running server.
        _refuse_if_incumbent_alive(state_dir)

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

    # Drop /health access-log spam (dashboard/CLI poll it every couple seconds —
    # it was ~95% of the captured stdout log volume).
    try:
        from brainpalace_server.logging_filters import (
            install_health_check_access_filter,
        )

        install_health_check_access_filter()
    except Exception as exc:  # noqa: BLE001 — never block startup on log filter
        logger.debug("Could not install health-check access filter: %s", exc)

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

    # Expose state for in-process self-registration / heal (self_heal.py).
    app.state.state_dir = str(state_dir) if state_dir else None
    app.state.registered_base_url = None

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
        # Surfaced by GET /index/fingerprint for the dashboard config save guard.
        app.state.storage_backend_name = backend_type
        app.state.graph_store_type = settings.GRAPH_STORE_TYPE
        logger.info("Storage backend initialized")

        # Index-drift warnings (visible in /health/status, `brainpalace status`,
        # and the dashboard). Embedding provider/model drift is detected above
        # (check_embedding_compatibility → app.state.embedding_warning); add a
        # storage-backend ("db type") drift check now that the backend is up.
        backend_drift = await check_storage_backend_drift(
            state_dir, backend_type, storage_backend
        )
        app.state.index_warnings = [
            w
            for w in (getattr(app.state, "embedding_warning", None), backend_drift)
            if w
        ]

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

        # Load exclude patterns from the indexing: block (config.yaml).
        # Previously read from config.json; now resolved via IndexingConfig (Task 11).
        from brainpalace_server.config.indexing_config import (  # noqa: PLC0415
            load_indexing_config,
        )

        _idx_cfg = load_indexing_config(
            (state_dir / "config.yaml") if state_dir else None
        )
        exclude_patterns: list[str] | None = _idx_cfg.exclude_patterns or None
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
        from brainpalace_server.config.indexing_config import load_indexing_config
        from brainpalace_server.indexing import DocumentLoader

        _indexing_cfg = load_indexing_config()
        document_loader = DocumentLoader(
            exclude_patterns=exclude_patterns,
            gitignore_matcher=gitignore_matcher,
            skip_minified=_indexing_cfg.skip_minified,
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
        # Exposed so the self-heal heartbeat can run the periodic deep-clean.
        app.state.manifest_tracker = manifest_tracker

        # Programmatic text-ingest service (spec Item 3 / G2). Built only when
        # embedding is available; a missing provider key leaves it None so the
        # POST /ingest/text endpoint returns an actionable 503 (Item-1 guardrail)
        # instead of crashing startup. Queries keep working regardless.
        app.state.document_ingest_service = None
        try:
            if storage_backend is not None:
                from brainpalace_server.indexing import get_embedding_generator
                from brainpalace_server.indexing.chunking import ContextAwareChunker
                from brainpalace_server.services.document_ingest_service import (
                    DocumentIngestService,
                )

                app.state.document_ingest_service = DocumentIngestService(
                    embedding_generator=get_embedding_generator(),
                    storage_backend=storage_backend,
                    chunker=ContextAwareChunker(),
                    bm25_manager=getattr(app.state, "bm25_manager", None),
                )
        except Exception:  # noqa: BLE001 — ingest is optional; queries still work
            logger.exception("text-ingest service unavailable")

        # Self-heal on every start. RECOVER FIRST, DESTROY LAST:
        #   stage 1 — restore lost chunks (code/doc AND git) from dead Chroma
        #     segments + the embedding cache — constructive, NO re-embed / no
        #     provider call (chunk_recovery). Replaces the old no-op
        #     reconcile_store_against_manifest.
        #   stage 2 (only if stage 1 fully succeeded): drop manifest records for
        #     files NOT fully recovered so they reindex like any unindexed file,
        #     heal folder records, then deep_clean (destructive purges). A failed
        #     or partial recovery keeps the gate CLOSED.
        # The reindex of dropped files is enqueued AFTER deep_clean, below, once
        # the job service exists. Never blocks startup.
        read_only = is_read_only()
        if read_only:
            logger.warning(
                "BrainPalace is in READ-ONLY mode: embedding, summarization, "
                "remote rerank and destructive self-heal are disabled."
            )
        heal_report: dict[str, Any] = {}
        try:
            from brainpalace_server.services.chunk_recovery import detect_dimensions
            from brainpalace_server.services.startup_reconcile import (
                self_heal_on_startup,
            )

            vector_store = getattr(app.state, "vector_store", None)
            target_dimensions = detect_dimensions(
                cache_db_path=cache_db_path, vector_store=vector_store
            )
            heal_report = await self_heal_on_startup(
                folder_manager=folder_manager,
                manifest_tracker=manifest_tracker,
                storage_backend=storage_backend,
                vector_store=vector_store,
                cache_db_path=cache_db_path,
                target_dimensions=target_dimensions or 0,
                bm25_manager=getattr(app.state, "bm25_manager", None),
                repo_path=app.state.project_root or None,
                read_only=read_only,
            )
            # Persist the result so `brainpalace status` can surface it, and emit
            # a prominent startup notification when recovery actually ran.
            _record_self_heal_result(
                heal_report, getattr(vector_store, "persist_dir", None)
            )

            # Automatic dead-row compaction — ONLY when this start verified the
            # index complete: nothing missing, nothing marked pending reindex,
            # stage 2 not skipped. Dead rows are the chunk-recovery fuel, so a
            # store with anything left to recover keeps them; a clean, heavily
            # bloated store (several stranded index generations) gets rebuilt
            # from live data and shrunk — no re-embed, threshold-gated so a
            # healthy store pays nothing. Runs BEFORE the memories collection
            # opens its handle on the same persist dir.
            _rec = heal_report.get("recovery")
            _index_complete = (
                not read_only
                and heal_report.get("deep_clean_skipped_reason") is None
                and not heal_report.get("files_dropped")
                and not heal_report.get("reindex_enqueued")
                and (_rec is None or getattr(_rec, "wanted", 0) == 0)
                and getattr(_rec, "error", None) is None
            )
            if _index_complete and vector_store is not None:
                await vector_store.compact_if_bloated()
        except Exception as exc:  # noqa: BLE001 — heal must never block startup
            logger.warning("Startup self-heal failed (non-fatal): %s", exc)

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
            # Exposed so the self-heal heartbeat can recompact this collection
            # too (not just the code index) on its periodic tick.
            app.state.mem_vector_store = mem_vector_store
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

        # Per-chunk extraction pending queue (Unified Extraction, Plan 2).
        # MUST be constructed BEFORE the session-reconciler block below: that
        # block (archive ON by default) builds the doc adapter referencing
        # app.state.doc_pending_store, so the attribute has to exist (store or
        # None) by then or the whole session setup aborts on AttributeError.
        try:
            from brainpalace_server.storage.extraction_pending import DocPendingStore

            app.state.doc_pending_store = DocPendingStore(
                db_path(state_dir, "extraction_pending.db")
            )
            # Wire the pending store into the graph index manager used by the job
            # worker so doc chunks are deferred (not extracted inline at index time).
            if (
                hasattr(app.state, "indexing_service")
                and app.state.indexing_service is not None
            ):
                app.state.indexing_service.graph_index_manager.pending_store = (
                    app.state.doc_pending_store
                )
        except Exception as exc:  # noqa: BLE001 — never block startup
            app.state.doc_pending_store = None
            logger.warning("DocPendingStore setup failed: %s", exc)

        # Shared extraction engine (Plan 4) — resolve mode/flags ONCE here and
        # stash on app.state. Adapters/endpoints/health read app.state.* (never
        # re-read config per call). A key/config change needs a restart to refresh
        # (consistent with how every other config applies). This is the C1
        # keystone: the doc drain is decoupled from sessions via these values.
        from brainpalace_server.config.extraction_config import (
            extraction_provider_enabled,
            load_extraction_config,
            resolve_extraction_mode,
        )

        _ext = load_extraction_config()
        app.state.extraction_mode_doc = resolve_extraction_mode("doc")
        app.state.extraction_mode_session = resolve_extraction_mode("session")
        app.state.extraction_provider_enabled = extraction_provider_enabled()
        app.state.extraction_grace_hours = _ext.grace_hours
        app.state.extraction_drain_batch = _ext.drain_batch_size
        app.state.extraction_drain_cooldown = _ext.drain_cooldown_seconds
        # graphrag.enabled maps onto ENABLE_GRAPH_INDEX at load (env wins).
        app.state.graphrag_enabled = bool(getattr(settings, "ENABLE_GRAPH_INDEX", True))
        # Provider availability for status (C2, key-present, no network).
        _sm = load_provider_settings().summarization
        app.state.summarization_label = (
            f"{_sm.provider}:{_sm.model}"
            if _sm and getattr(_sm, "model", None)
            else (getattr(_sm, "provider", None) if _sm else None)
        )
        app.state.summarization_available = bool(
            _sm
            and (
                str(getattr(_sm, "provider", "")).lower() == "ollama"
                or _sm.get_api_key()
            )
        )

        # Doc-graph provider drain runs INDEPENDENT of session capabilities
        # (C1/§4): graphrag on + provider/auto mode + the H2 provider lock +
        # a pending store + writable. Two cost locks: mode AND env (H2).
        doc_extraction_would_run = (
            app.state.graphrag_enabled
            and app.state.extraction_mode_doc in ("provider", "auto")
            and app.state.extraction_provider_enabled
            and app.state.doc_pending_store is not None
            and not read_only
        )

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

            # Server-side summarization (provider/auto) is INDEPENDENT of archive
            # and index: set it up whenever extraction would run, even if both of
            # those are OFF, so the three capabilities work individually.
            from brainpalace_server.config.session_config import (
                load_session_extraction_config,
                session_distill_grace_hours,
            )

            # extraction.mode (stashed in app.state.extraction_mode_session) governs
            # both doc-graph and session consumers; the shared provider lock is the
            # second billable gate (mode ∈ {provider,auto} AND the env lock).
            # extract_cfg supplies only quiescence_seconds (session-only timing gate).
            extract_cfg = load_session_extraction_config()
            distill_would_run = (
                app.state.extraction_mode_session in ("provider", "auto")
                and app.state.extraction_provider_enabled
                and bool(app.state.project_root)
                and not read_only
            )

            if (
                caps.archive_enabled
                or caps.index_enabled
                or distill_would_run
                or doc_extraction_would_run
            ) and app.state.project_root:
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

                # Existence-based purge of orphaned session + git chunks (their
                # source transcript / commit is gone). Runs once at startup; the
                # heartbeat repeats it on an idle tick. Best-effort.
                try:
                    from brainpalace_server.services.startup_reconcile import (
                        DeepCleanSummary,
                        prune_orphan_git_chunks,
                        prune_orphan_session_chunks,
                    )

                    _purge = DeepCleanSummary()
                    await prune_orphan_session_chunks(
                        storage_backend,
                        getattr(archive_service, "archive_dir", None),
                        _purge,
                    )
                    await prune_orphan_git_chunks(
                        storage_backend, app.state.project_root or None, _purge
                    )
                except Exception as exc:  # noqa: BLE001 — never block startup
                    logger.warning("Session/git orphan purge failed: %s", exc)

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
                app.state.memory_curator = None
                try:
                    extract_mode = app.state.extraction_mode_session
                    if distill_would_run:
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
                        from brainpalace_server.config.model_windows import (
                            resolve_chunk_chars,
                        )
                        from brainpalace_server.services.provider_budget import (
                            is_billable,
                        )

                        _proj = app.state.project_root
                        _summ_settings = load_provider_settings().summarization
                        _summ_provider = str(getattr(_summ_settings, "provider", ""))
                        _summ_model = str(getattr(_summ_settings, "model", ""))
                        _chunk_chars = resolve_chunk_chars(
                            provider_context_tokens=_ext.provider_context_tokens,
                            distill_chunk_chars=_ext.distill_chunk_chars,
                            provider=_summ_provider,
                            model=_summ_model,
                        )
                        distiller = _distill.SessionDistiller(
                            summarizer=ProviderRegistry.get_summarization_provider(
                                _summ_settings
                            ),
                            embedder=get_embedding_generator(),
                            storage_backend=storage_backend,
                            project_root=_proj,
                            graph_store=distill_graph,
                            memory_service=app.state.memory_service,
                            digest_path=str(Path(_proj) / "BRAINPALACE_DECISIONS.md"),
                            mode=extract_mode,
                            idle_seconds=extract_cfg.quiescence_seconds,
                            chunk_chars=_chunk_chars,
                            plugin_present=lambda: claude_plugin_installed(
                                project=Path(_proj)
                            ),
                            grace_hours=session_distill_grace_hours(),
                            record_store=app.state.record_store,
                            max_chunks=(
                                _ext.provider_session_max_chunks
                                if is_billable(_summ_settings)
                                else 0
                            ),
                            server_start_ts=app.state.server_start_ts,
                            first_request_seen=lambda: bool(
                                getattr(app.state, "first_request_seen", False)
                            ),
                        )
                        app.state.session_distiller = distiller
                        logger.info(
                            "Session distiller enabled (engine=%s).", extract_mode
                        )

                        # Provider-mode memory curation shares the summarization
                        # provider + the extraction cost-lock. subagent/auto's
                        # in-session path is the SessionStart nudge (curate_due); the
                        # server only curates when a paid/local provider is authorized.
                        from brainpalace_server.config.extraction_config import (
                            extraction_provider_enabled,
                        )

                        if (
                            extract_mode in ("provider", "auto")
                            and extraction_provider_enabled()
                            and app.state.memory_service is not None
                        ):
                            from brainpalace_server.services.memory_curator_service import (  # noqa: E501
                                MemoryCurator,
                            )

                            app.state.memory_curator = MemoryCurator(
                                summarizer=ProviderRegistry.get_summarization_provider(
                                    _summ_settings
                                ),
                                memory_service=app.state.memory_service,
                            )
                        else:
                            app.state.memory_curator = None
                except Exception as exc:  # noqa: BLE001 — never block startup
                    logger.warning("Session distiller setup failed: %s", exc)

                # Periodic reconcile: archives always, indexes only when enabled.
                # The first tick runs immediately (the boot sweep — sync + index +
                # distiller catch-up); thereafter copy cadence is
                # session_archive.reconcile_seconds. Per-event copy is retired, so a
                # growing session is re-copied at most once per interval (the final
                # tail is captured on the first sweep after it goes quiet).
                if (
                    archive_service is not None
                    or sess_svc is not None
                    or distiller is not None
                    or doc_extraction_would_run
                ):
                    # Ordering contract (2-8): the doc adapter + reconciler below
                    # consume the Plan 4 lifespan-resolved extraction state
                    # (app.state.extraction_*) and the doc_pending_store, both wired
                    # EARLIER in this block. Fail fast + loud if a future reorder
                    # moves this ahead of the resolution, instead of silently
                    # mis-wiring the drain (the df359c4c class of bug). Cheap check,
                    # not stripped under -O.
                    if not hasattr(app.state, "extraction_mode_doc") or not hasattr(
                        app.state, "extraction_drain_batch"
                    ):
                        raise RuntimeError(
                            "extraction engine not resolved before reconciler wiring "
                            "— resolve mode/flags onto app.state first (lifespan "
                            "ordering bug)"
                        )

                    from brainpalace_server.providers.factory import ProviderRegistry
                    from brainpalace_server.services.doc_extraction_adapter import (
                        DocExtractionAdapter,
                    )
                    from brainpalace_server.services.session_extraction_adapter import (
                        SessionExtractionAdapter,
                    )
                    from brainpalace_server.services.session_reconciler import (
                        ExtractionDrainState,
                        SessionReconciler,
                    )
                    from brainpalace_server.storage.graph_store import (
                        get_graph_store_manager,
                    )

                    _archive_dir_str = (
                        str(archive_service.archive_dir)
                        if archive_service is not None
                        else str(app.state.project_root)
                    )
                    app.state.extraction_archive_dir = (
                        _archive_dir_str  # for /extraction/pending session gap
                    )

                    def _make_doc_provider() -> Any:
                        return ProviderRegistry.get_summarization_provider(
                            load_provider_settings().summarization
                        )

                    doc_adapter = (
                        DocExtractionAdapter(
                            store=app.state.doc_pending_store,
                            graph_store=get_graph_store_manager(),
                            provider_factory=_make_doc_provider,
                            graphrag_enabled=app.state.graphrag_enabled,
                            mode=app.state.extraction_mode_doc,
                            provider_enabled=app.state.extraction_provider_enabled,
                            grace_hours=app.state.extraction_grace_hours,
                            project_root=str(app.state.project_root),
                            server_start_ts=app.state.server_start_ts,
                            first_request_seen=lambda: bool(
                                getattr(app.state, "first_request_seen", False)
                            ),
                        )
                        if app.state.doc_pending_store is not None
                        else None
                    )
                    session_adapter = SessionExtractionAdapter(
                        distiller=distiller,
                        project_root=str(app.state.project_root),
                        archive_dir=_archive_dir_str,
                    )
                    adapters = [
                        a for a in (doc_adapter, session_adapter) if a is not None
                    ]

                    # Task 4b: billable-only per-hour provider spend cap. Skipped
                    # for keyless/local providers (Ollama) — no $ cost.
                    from brainpalace_server.services.provider_budget import (
                        ProviderBudget,
                        is_billable,
                    )

                    _provider_billable = is_billable(_sm)
                    _provider_budget = (
                        ProviderBudget(_ext.max_provider_items_per_hour)
                        if _provider_billable
                        else None
                    )

                    reconciler = SessionReconciler(
                        interval_seconds=session_cfg.archive.reconcile_seconds,
                        sessions_dir=sessions_dir,
                        archive_service=archive_service,
                        sess_svc=sess_svc,
                        session_cfg=session_cfg,
                        caps=caps,
                        distiller=distiller,
                        adapters=adapters,
                        drain_state=ExtractionDrainState(),
                        drain_max_count=app.state.extraction_drain_batch,
                        drain_cooldown=app.state.extraction_drain_cooldown,
                        provider_budget=_provider_budget,
                        provider_billable=_provider_billable,
                        memory_curator=getattr(app.state, "memory_curator", None),
                        curate_state_dir=state_dir,
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
                logger.info("Git indexing enabled: %s", app.state.project_root)
        except Exception as exc:  # noqa: BLE001 — never block startup on git
            logger.warning("Git indexing setup failed: %s", exc)

        # Task 9: construct RecordStore (one per server lifetime, SQLite WAL).
        try:
            from brainpalace_server.storage.record_store import RecordStore

            _records_db = db_path(state_dir, "records.db")
            app.state.record_store = RecordStore(_records_db)
            logger.info("RecordStore initialized: %s", _records_db)
        except Exception as exc:  # noqa: BLE001 — never block startup
            app.state.record_store = None
            logger.warning("RecordStore setup failed: %s", exc)

        # Phase 6: lazy-tier reference catalog (SQLite WAL) + register the
        # session record adapter into the in-memory ingestion registry.
        try:
            from brainpalace_server.storage.reference_catalog_store import (  # noqa: PLC0415
                ReferenceCatalogStore,
            )

            _refcat_db = db_path(state_dir, "reference_catalog.db")
            app.state.reference_catalog_store = ReferenceCatalogStore(_refcat_db)
            logger.info("ReferenceCatalogStore initialized: %s", _refcat_db)
        except Exception as exc:  # noqa: BLE001 — never block startup
            app.state.reference_catalog_store = None
            logger.warning("ReferenceCatalogStore setup failed: %s", exc)

        # G5: identity store (person / alias / link) — user-asserted ground
        # truth in its own SQLite file (D1). None-safe: the /entities router
        # 503s and the ingest cascade no-ops when it failed to build.
        try:
            from brainpalace_server.storage.identity_store import (  # noqa: PLC0415
                IdentityStore,
            )

            _identity_db = db_path(state_dir, "identity.db")
            app.state.identity_store = IdentityStore(_identity_db)
            logger.info("IdentityStore initialized: %s", _identity_db)
            # Wire it into the (already-built) ingest service so the G5 Task 6
            # delete/re-ingest cascade reaches a live store. The service is
            # constructed earlier in lifespan than this store, so bind here.
            _ingest = getattr(app.state, "document_ingest_service", None)
            if _ingest is not None:
                _ingest.identity_store = app.state.identity_store
        except Exception as exc:  # noqa: BLE001 — never block startup
            app.state.identity_store = None
            logger.warning("IdentityStore setup failed: %s", exc)

        try:
            from brainpalace_server.ingestion.adapter import (  # noqa: PLC0415
                register_adapter,
                reset_adapters,
            )
            from brainpalace_server.services.session_records import (  # noqa: PLC0415
                SessionRecordAdapter,
            )

            reset_adapters()  # deterministic registry across reloads
            register_adapter(SessionRecordAdapter())
            logger.info("Ingestion adapters registered: session")
        except Exception as exc:  # noqa: BLE001 — never block startup
            logger.warning("Adapter registration failed: %s", exc)

        # Phase 5: durable taught-rule store — load persisted rules into the
        # validator registry on start (reset first for a deterministic list).
        try:
            from brainpalace_server.indexing.record_validation import (  # noqa: PLC0415
                reset_validators,
            )
            from brainpalace_server.indexing.taught_rules import (  # noqa: PLC0415
                load_taught_rules,
            )
            from brainpalace_server.storage.taught_rule_store import (  # noqa: PLC0415
                TaughtRuleStore,
            )

            reset_validators()
            _rules_db = db_path(state_dir, "rules.db")
            app.state.taught_rule_store = TaughtRuleStore(_rules_db)
            _loaded = load_taught_rules(app.state.taught_rule_store)
            logger.info(
                "TaughtRuleStore initialized: %s (%d rules)", _rules_db, _loaded
            )
        except Exception as exc:  # noqa: BLE001 — never block startup
            app.state.taught_rule_store = None
            logger.warning("TaughtRuleStore setup failed: %s", exc)

        # Usage telemetry store (own sqlite file; best-effort; gated by config).
        try:
            from brainpalace_server.config.usage_metrics_config import (  # noqa: PLC0415
                load_usage_metrics_config,
            )
            from brainpalace_server.services.usage_metrics import (  # noqa: PLC0415
                set_usage_store,
            )
            from brainpalace_server.storage.usage_metrics_store import (  # noqa: PLC0415
                UsageMetricsStore,
            )

            _um_cfg = load_usage_metrics_config()
            app.state.usage_metrics_config = _um_cfg
            if _um_cfg.enabled and state_dir is not None:
                _um_db = db_path(state_dir, "usage_metrics.db")
                _um_store = UsageMetricsStore(_um_db)
                _um_store.prune(int(time.time()) // 60, _um_cfg.retain_days)
                set_usage_store(_um_store)
                app.state.usage_metrics_store = _um_store
                logger.info("Usage metrics store initialized: %s", _um_db)
            else:
                app.state.usage_metrics_store = None
                logger.info("Usage metrics disabled")
        except Exception as exc:  # noqa: BLE001 — telemetry must never block startup
            app.state.usage_metrics_store = None
            logger.warning("Usage metrics store setup failed: %s", exc)

        # Wire the usage metrics store into the session reconciler for tick-prune
        # (§6-F6): the reconciler is constructed before the store, so we set it
        # after both are ready. Best-effort — a missing reconciler is a no-op.
        _recon = getattr(app.state, "session_reconciler", None)
        if _recon is not None and app.state.usage_metrics_store is not None:
            try:
                _recon._usage_metrics_store = app.state.usage_metrics_store
                _recon._usage_metrics_retain_days = (
                    getattr(app.state, "usage_metrics_config", None)
                    and app.state.usage_metrics_config.retain_days
                    or 30
                )
            except Exception:  # noqa: BLE001
                pass

        # Phase 6.5a: load per-project ranking config (doc_weight) from config.yaml.
        try:
            from brainpalace_server.config.provider_config import (  # noqa: PLC0415
                load_merged_config_dict,
            )
            from brainpalace_server.config.ranking_config import (  # noqa: PLC0415
                RankingConfig,
            )

            _merged = load_merged_config_dict(
                (state_dir / "config.yaml") if state_dir else None
            )
            app.state.ranking_config = RankingConfig(**(_merged.get("ranking") or {}))
        except Exception as exc:  # noqa: BLE001 — never block startup; default 0.5
            app.state.ranking_config = RankingConfig()
            # ERROR (not warning): a swallowed config-load failure once shipped a
            # silently-dead doc_weight. Loud so a real failure can't hide again.
            logger.error("RankingConfig load failed, using default 0.5: %s", exc)

        # Task 5 (6.5): load the project's own domain (config.yaml `project:`
        # section, default "code"). Threaded into JobQueueService below so
        # folders default their domain to it and an external folder claiming
        # this same domain triggers the --force gate.
        try:
            from brainpalace_server.config.project_config import (  # noqa: PLC0415
                ProjectConfig,
            )

            _project_cfg_dict = load_merged_config_dict(
                (state_dir / "config.yaml") if state_dir else None
            )
            app.state.project_domain = ProjectConfig(
                **(_project_cfg_dict.get("project") or {})
            ).domain
        except Exception as exc:  # noqa: BLE001 — never block startup; default "code"
            app.state.project_domain = "code"
            logger.warning("ProjectConfig load failed, using default 'code': %s", exc)

        # Create query service with storage_backend (Phase 9)
        query_service = QueryService(
            storage_backend=storage_backend,
            query_cache=query_cache,
            memory_service=memory_service,
            record_store=app.state.record_store,
            archive_dir=getattr(
                getattr(app.state, "session_archive_service", None),
                "archive_dir",
                None,
            ),
            ranking_config=app.state.ranking_config,
            reference_catalog_store=getattr(app.state, "reference_catalog_store", None),
            identity_store=getattr(app.state, "identity_store", None),
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
                    db_path(state_dir, "query_log.db"),
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
                project_domain=getattr(app.state, "project_domain", None),
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
            # Task 4d: wire backpressure store so the worker can check the
            # extraction-pending queue depth before scheduling new file batches.
            _job_worker.set_doc_pending_store(
                getattr(app.state, "doc_pending_store", None)
            )
            # Task 4d: wire backpressure store to file-watcher so watch-triggered
            # enqueues are skipped when the extraction queue is at high-water.
            _file_watcher.set_doc_pending_store(
                getattr(app.state, "doc_pending_store", None)
            )
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
                project_domain=getattr(app.state, "project_domain", None),
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
            # Task 4d: wire backpressure store (no-state-dir path)
            _job_worker.set_doc_pending_store(
                getattr(app.state, "doc_pending_store", None)
            )
            # Task 4d: wire backpressure store to file-watcher (no-state-dir path)
            _file_watcher.set_doc_pending_store(
                getattr(app.state, "doc_pending_store", None)
            )

        # Wire JobWorker git deps + enqueue boot git-history job (Issue #15).
        # Runs after both the state-dir and no-state-dir branches have started
        # the worker, so _job_worker and job_service are always set by here.
        if _job_worker is not None:
            _job_worker.set_git_service(
                app.state.git_index_service,
                app.state.git_indexing_config,
                app.state.project_root or None,
            )

        if app.state.git_index_service is not None and app.state.project_root:
            try:
                resp = await job_service.enqueue_git_history_job(app.state.project_root)
                logger.info(
                    "Git boot-index enqueued: job_id=%s dedupe_hit=%s",
                    resp.job_id,
                    resp.dedupe_hit,
                )
            except Exception as exc:  # noqa: BLE001 — never block startup on git
                logger.warning("Git boot-index enqueue failed: %s", exc)

        # Reindex the files self-heal dropped (not-fully-recovered) — AFTER
        # deep_clean and once the job service + worker exist. force=False so the
        # incremental index only re-creates the dropped/new files; their
        # embeddings come from the cache, only the genuinely-gone residue calls
        # the provider. Never blocks startup.
        dropped_folders = heal_report.get("dropped_folders") or []
        if dropped_folders and job_service is not None:
            try:
                from brainpalace_server.services.startup_reconcile import (
                    _enqueue_folder_reindex,
                )

                heal_report["reindex_enqueued"] = await _enqueue_folder_reindex(
                    job_service, folder_manager, dropped_folders
                )
            except Exception as exc:  # noqa: BLE001 — never block startup
                logger.warning("Self-heal reindex enqueue failed: %s", exc)

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

    # Start the self-heal heartbeat (re-asserts registration + heals dependents).
    from brainpalace_server import self_heal

    app.state._heartbeat_task = asyncio.create_task(self_heal.heartbeat_loop(app))

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

    # Close usage metrics store and deregister the recorder.
    _um_store_shutdown = getattr(app.state, "usage_metrics_store", None)
    if _um_store_shutdown is not None:
        try:
            from brainpalace_server.services.usage_metrics import set_usage_store

            set_usage_store(None)
            _um_store_shutdown.close()
            logger.info("Usage metrics store closed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Usage metrics store close failed: %s", exc)

    # Close storage backend if it has a close method (PostgreSQL pool)
    shutdown_backend = getattr(app.state, "storage_backend", None)
    if shutdown_backend is not None and hasattr(shutdown_backend, "close"):
        await shutdown_backend.close()
        logger.info("Storage backend connection pool closed")

    # Stop the self-heal heartbeat.
    hb = getattr(app.state, "_heartbeat_task", None)
    if hb is not None:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass

    # Deregister from the global registry on clean shutdown.
    if state_dir is not None:
        from brainpalace_server import registry as _registry

        project_root_for_dereg = (
            Path(app.state.project_root) if app.state.project_root else None
        )
        if project_root_for_dereg:
            _registry.remove_entry(project_root_for_dereg)

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

# In-process self-registration: learn the bound address from incoming requests
# and write runtime.json + registry.json off the response path (self_heal.py).
from collections.abc import Awaitable, Callable  # noqa: E402

from starlette.requests import Request  # noqa: E402
from starlette.responses import Response  # noqa: E402

from brainpalace_server import self_heal  # noqa: E402


@app.middleware("http")
async def _self_heal_registration(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # Task 4f cold-start gate: the auto-grace provider drain never runs until the
    # system is live (a request has arrived). Cheap + idempotent.
    app.state.first_request_seen = True
    return await self_heal.registration_middleware(app)(request, call_next)


_self_heal_wired = True

# Include routers
app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(index_router, prefix="/index", tags=["Indexing"])
app.include_router(cache_router, prefix="/index/cache", tags=["Cache"])
app.include_router(folders_router, prefix="/index/folders", tags=["Folders"])
app.include_router(jobs_router, prefix="/index/jobs", tags=["Jobs"])
app.include_router(query_router, prefix="/query", tags=["Querying"])
app.include_router(runtime_router, prefix="/runtime", tags=["Runtime"])
app.include_router(records_router, prefix="/records", tags=["Records"])
app.include_router(ingest_router, prefix="/ingest", tags=["Ingest"])
app.include_router(rules_router, prefix="/rules", tags=["Rules"])
from brainpalace_server.api.routers.references import (  # noqa: E402 — late import, registered after app setup
    router as references_router,
)

app.include_router(references_router, prefix="/references", tags=["References"])
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
from brainpalace_server.api.routers.graph import (  # noqa: E402 — late import, registered after app setup
    router as graph_browse_router,
)

app.include_router(graph_browse_router, prefix="/graph", tags=["Graph"])
from brainpalace_server.api.routers.extraction import (  # noqa: E402 — late import, registered after app setup
    router as extraction_router,
)

app.include_router(extraction_router, prefix="/extraction", tags=["Extraction"])
from brainpalace_server.api.routers.metrics import (  # noqa: E402 — late import, registered after app setup
    router as metrics_router,
)

app.include_router(metrics_router, prefix="/metrics", tags=["Metrics"])
from brainpalace_server.api.routers.entities import (  # noqa: E402 — late import, registered after app setup
    router as entities_router,
)

app.include_router(entities_router, prefix="/entities", tags=["Entities"])


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

        # runtime.json is no longer written here: the running server registers
        # itself in-process (self_heal middleware/heartbeat) from the bound
        # socket on the first request, so every launch path is covered. We keep
        # _runtime_state (its instance_id/project_id feed the health endpoint).
        _state_dir.mkdir(parents=True, exist_ok=True)
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
