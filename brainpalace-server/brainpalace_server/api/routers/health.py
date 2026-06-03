"""Health check endpoints with non-blocking queue status."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from brainpalace_server import __version__
from brainpalace_server.config.provider_config import (
    _find_config_file,
    load_provider_settings,
    validate_provider_config,
)
from brainpalace_server.config.session_config import load_session_extraction_config
from brainpalace_server.models import HealthStatus, IndexingStatus
from brainpalace_server.models.health import ProviderHealth, ProvidersStatus
from brainpalace_server.providers.factory import ProviderRegistry
from brainpalace_server.storage import get_effective_backend_type

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=HealthStatus,
    summary="Health Check",
    description="Returns the current server health status.",
)
async def health_check(request: Request) -> HealthStatus:
    """Check server health status.

    This endpoint never blocks and always returns quickly.

    Returns:
        HealthStatus with current status:
        - healthy: Server is running and ready for queries
        - indexing: Server is currently indexing documents
        - degraded: Server is up but some services are unavailable
        - unhealthy: Server is not operational
    """
    vector_store = getattr(request.app.state, "vector_store", None)
    job_service = getattr(request.app.state, "job_service", None)

    # Determine status using queue service (non-blocking)
    status: Literal["healthy", "indexing", "degraded", "unhealthy"]
    message: str

    # Check queue status (non-blocking)
    is_indexing = False
    current_folder = None
    if job_service:
        try:
            queue_stats = await job_service.get_queue_stats()
            is_indexing = queue_stats.running > 0
            if is_indexing and queue_stats.current_job_id:
                # Get current job details for message
                current_job = await job_service.get_job(queue_stats.current_job_id)
                if current_job:
                    current_folder = current_job.folder_path
        except Exception:
            # Non-blocking: don't fail health check if queue service errors
            pass

    if is_indexing:
        status = "indexing"
        message = f"Indexing in progress: {current_folder or 'unknown'}"
    elif vector_store is None:
        # Non-chroma backend -- check storage_backend directly
        storage_backend = getattr(request.app.state, "storage_backend", None)
        if storage_backend and storage_backend.is_initialized:
            status = "healthy"
            message = "Server is running and ready for queries"
        else:
            status = "degraded"
            message = "Storage backend not initialized"
    elif not vector_store.is_initialized:
        status = "degraded"
        message = "Vector store not initialized"
    else:
        status = "healthy"
        message = "Server is running and ready for queries"

    # Multi-instance metadata
    mode = getattr(request.app.state, "mode", "project")
    instance_id = getattr(request.app.state, "instance_id", None)
    project_id = getattr(request.app.state, "project_id", None)
    active_projects = getattr(request.app.state, "active_projects", None)

    return HealthStatus(
        status=status,
        message=message,
        timestamp=datetime.now(timezone.utc),
        version=__version__,
        mode=mode,
        instance_id=instance_id,
        project_id=project_id,
        active_projects=active_projects,
    )


@router.get(
    "/status",
    summary="Indexing Status",
    description="Returns detailed indexing status information. Never blocks.",
)
async def indexing_status(request: Request) -> dict[str, Any]:
    """Get detailed indexing status.

    This endpoint never blocks and always returns quickly, even during indexing.

    Returns:
        IndexingStatus with:
        - total_documents: Number of documents indexed
        - total_chunks: Number of chunks in vector store
        - indexing_in_progress: Boolean indicating active indexing
        - queue_pending: Number of pending jobs
        - queue_running: Number of running jobs (0 or 1)
        - current_job_running_time_ms: How long current job has been running
        - last_indexed_at: Timestamp of last indexing operation
        - indexed_folders: List of folders that have been indexed
    """
    indexing_service = request.app.state.indexing_service
    vector_store = getattr(request.app.state, "vector_store", None)
    job_service = getattr(request.app.state, "job_service", None)

    # Get chunk count — prefer storage_backend (single source of truth)
    # over legacy vector_store which may be a separate Chroma instance.
    try:
        storage_backend = getattr(request.app.state, "storage_backend", None)
        if storage_backend and storage_backend.is_initialized:
            total_chunks = await storage_backend.get_count()
        elif vector_store is not None and vector_store.is_initialized:
            total_chunks = await vector_store.get_count()
        else:
            total_chunks = 0
    except Exception:
        total_chunks = 0

    # Get queue status (non-blocking)
    queue_pending = 0
    queue_running = 0
    current_job_id = None
    current_job_running_time_ms = None
    progress_percent = 0.0

    if job_service:
        try:
            queue_stats = await job_service.get_queue_stats()
            queue_pending = queue_stats.pending
            queue_running = queue_stats.running
            current_job_id = queue_stats.current_job_id
            current_job_running_time_ms = queue_stats.current_job_running_time_ms

            # Get progress from current job
            if current_job_id:
                current_job = await job_service.get_job(current_job_id)
                if current_job and current_job.progress:
                    progress_percent = current_job.progress.percent_complete
        except Exception:
            # Non-blocking: don't fail status if queue service errors
            pass

    # Get indexing service status for historical data
    # This is read-only and non-blocking
    service_status = await indexing_service.get_status()

    # Override graph index status when on non-chroma backend
    backend_type = get_effective_backend_type()
    graph_index_info = service_status.get("graph_index")
    if backend_type != "chroma" and graph_index_info is not None:
        reason_msg = f"Graph queries require ChromaDB backend (current: {backend_type})"
        graph_index_info = {
            "enabled": False,
            "initialized": False,
            "entity_count": 0,
            "relationship_count": 0,
            "store_type": "unavailable",
            "reason": reason_msg,
        }
        service_status["graph_index"] = graph_index_info

    # Get file watcher status (Phase 15)
    file_watcher_service = getattr(request.app.state, "file_watcher_service", None)
    file_watcher_info: dict[str, Any] = {
        "running": (file_watcher_service.is_running if file_watcher_service else False),
        "watched_folders": (
            file_watcher_service.watched_folder_count if file_watcher_service else 0
        ),
    }

    # Get embedding cache status (Phase 16)
    # Only include when cache has entries (omit for fresh installs)
    embedding_cache_info: dict[str, Any] | None = None
    embedding_cache_svc = getattr(request.app.state, "embedding_cache", None)
    if embedding_cache_svc is not None:
        try:
            disk_stats = await embedding_cache_svc.get_disk_stats()
            if disk_stats.get("entry_count", 0) > 0:
                mem_stats = embedding_cache_svc.get_stats()
                embedding_cache_info = {**mem_stats, **disk_stats}
        except Exception:
            # Non-blocking: don't fail status if cache stats error
            pass

    # Query cache stats (Phase 17)
    query_cache_info: dict[str, Any] | None = None
    query_cache_svc = getattr(request.app.state, "query_cache", None)
    if query_cache_svc is not None:
        query_cache_info = query_cache_svc.get_stats()

    response = IndexingStatus(
        total_documents=await indexing_service.get_document_count(),
        total_chunks=total_chunks,
        total_doc_chunks=service_status.get("total_doc_chunks", 0),
        total_code_chunks=service_status.get("total_code_chunks", 0),
        indexing_in_progress=queue_running > 0,
        current_job_id=current_job_id,
        progress_percent=progress_percent,
        last_indexed_at=(
            datetime.fromisoformat(service_status["completed_at"])
            if service_status.get("completed_at")
            else None
        ),
        indexed_folders=service_status.get("indexed_folders", []),
        supported_languages=service_status.get("supported_languages", []),
        graph_index=service_status.get("graph_index"),
        # Queue status (Feature 115)
        queue_pending=queue_pending,
        queue_running=queue_running,
        current_job_running_time_ms=current_job_running_time_ms,
        # File watcher status (Phase 15)
        file_watcher=file_watcher_info,
        # Embedding cache status (Phase 16)
        embedding_cache=embedding_cache_info,
        # Query cache status (Phase 17)
        query_cache=query_cache_info,
    )

    # Always serialize via model_dump so we can narrowly omit
    # embedding_cache when None (fresh installs) without response_model
    # re-adding it as null.
    data = response.model_dump(mode="json")
    if embedding_cache_info is None:
        data.pop("embedding_cache", None)

    # Phase 050 — session_turn chunk count (feeds `doctor` collection_sizes).
    # Best-effort: omit silently if the backend can't filter by metadata.
    try:
        backend = getattr(request.app.state, "storage_backend", None)
        if backend is not None and backend.is_initialized:
            data["session_chunks"] = await backend.get_count(
                where={"source_type": "session_turn"}
            )
    except Exception:  # noqa: BLE001 — never fail /status on the optional count
        pass

    # Phase 130 — git_commit chunk count (fills the 040 collection_sizes
    # placeholder). Best-effort: omit silently if the backend can't filter.
    try:
        backend = getattr(request.app.state, "storage_backend", None)
        if backend is not None and backend.is_initialized:
            data["git_commits"] = await backend.get_count(
                where={"source_type": "git_commit"}
            )
    except Exception:  # noqa: BLE001 — never fail /status on the optional count
        pass

    # Consolidated per-feature status for `brainpalace status` (human view).
    # Reuses values already computed above; tolerant of missing app.state.
    session_cfg = getattr(request.app.state, "session_indexing_config", None)
    session_watcher = getattr(request.app.state, "session_watcher", None)
    archive_enabled = bool(getattr(request.app.state, "session_archive_enabled", False))
    index_enabled = bool(getattr(request.app.state, "session_index_enabled", False))
    memory_service = getattr(request.app.state, "memory_service", None)
    curated_count = 0
    if memory_service is not None:
        try:
            curated_count = len(memory_service.load())
        except Exception:  # noqa: BLE001
            curated_count = 0

    archive_service = getattr(request.app.state, "session_archive_service", None)
    archive_stats = {
        "archived_sessions": 0,
        "archived_files": 0,
        "archived_bytes": 0,
        "tombstoned": 0,
    }
    if archive_service is not None:
        try:
            archive_stats = archive_service.stats()
        except Exception:  # noqa: BLE001
            pass

    fw = file_watcher_info or {}
    data["features"] = {
        "doc_indexing": {
            "active": total_chunks > 0,
            "total_chunks": total_chunks,
            "total_documents": data.get("total_documents", 0),
        },
        "file_watcher": {
            "enabled": bool(fw.get("running")),
            "watched_folders": int(fw.get("watched_folders", 0) or 0),
        },
        # INDEX capability (embeddings). `enabled` stays index-scoped for
        # back-compat; archive lives in its own feature below.
        "session_memory": {
            "enabled": index_enabled,
            "watcher_running": bool(getattr(session_watcher, "is_running", False)),
            "session_chunks": int(data.get("session_chunks", 0) or 0),
            "curated_memories": curated_count,
            "archived_sessions": int(archive_stats["archived_sessions"]),
            "archived_files": int(
                archive_stats.get("archived_files", archive_stats["archived_sessions"])
            ),
            "archived_bytes": int(archive_stats["archived_bytes"]),
            "tombstoned": int(archive_stats["tombstoned"]),
        },
        # ARCHIVE capability (raw transcript backup) — independent of index.
        "session_archive": {
            "enabled": archive_enabled,
            "retain_days": int(
                getattr(getattr(session_cfg, "archive", None), "retain_days", 0) or 0
            ),
            "archived_sessions": int(archive_stats["archived_sessions"]),
            "archived_files": int(
                archive_stats.get("archived_files", archive_stats["archived_sessions"])
            ),
            "archived_bytes": int(archive_stats["archived_bytes"]),
            "tombstoned": int(archive_stats["tombstoned"]),
        },
        "graph_index": graph_index_info or {"enabled": False},
    }

    # Session summarization coverage: how many archived sessions have a durable
    # extraction (.done marker) vs the total archived. Engine-agnostic — both the
    # plugin subagent and the provider distiller write the unified marker.
    project_root = getattr(request.app.state, "project_root", "") or ""
    try:
        extract_mode = load_session_extraction_config().mode
    except Exception:  # noqa: BLE001
        extract_mode = "auto"
    data["features"]["session_extraction"] = summarization_coverage(
        project_root, int(archive_stats["archived_sessions"]), extract_mode
    )

    return data


def count_done_markers(project_root: str | Path) -> int:
    """Number of ``.done`` extraction markers under the project state dir."""
    if not project_root:
        return 0
    extracted_dir = Path(project_root) / ".brainpalace" / "extracted"
    if not extracted_dir.is_dir():
        return 0
    try:
        return sum(1 for _ in extracted_dir.glob("*.done"))
    except OSError:
        return 0


def summarization_coverage(
    project_root: str | Path, total_sessions: int, mode: str
) -> dict[str, Any]:
    """Build the ``session_extraction`` status feature block.

    ``summarized_pct`` is clamped to [0, 100] (marker count can exceed archived
    sessions — e.g. markers for sessions no longer archived).
    """
    summarized = count_done_markers(project_root)
    pct = (
        round(100.0 * min(summarized, total_sessions) / total_sessions, 1)
        if total_sessions
        else 0.0
    )
    return {
        "mode": mode,
        "summarized_sessions": summarized,
        "total_sessions": total_sessions,
        "summarized_pct": pct,
    }


@router.get(
    "/providers",
    response_model=ProvidersStatus,
    summary="Provider Status",
    description="Returns status of all configured providers with health checks.",
)
async def providers_status(request: Request) -> ProvidersStatus:
    """Get detailed status of all configured providers.

    Returns:
        ProvidersStatus with configuration source, validation errors,
        and health status of each provider.
    """
    # Get config source
    config_file = _find_config_file()
    config_source = str(config_file) if config_file else None

    # Get strict mode from app state
    strict_mode = getattr(request.app.state, "strict_mode", False)

    # Load settings and validate
    settings = load_provider_settings()
    validation_errors = validate_provider_config(settings)
    error_messages = [str(e) for e in validation_errors]

    providers: list[ProviderHealth] = []

    # Check embedding provider
    try:
        embedding_provider = ProviderRegistry.get_embedding_provider(settings.embedding)
        embedding_status = "healthy"
        embedding_message = None
        embedding_dimensions = embedding_provider.get_dimensions()
    except Exception as e:
        embedding_status = "unavailable"
        embedding_message = str(e)
        embedding_dimensions = None

    providers.append(
        ProviderHealth(
            provider_type="embedding",
            provider_name=str(settings.embedding.provider),
            model=settings.embedding.model,
            status=embedding_status,
            message=embedding_message,
            dimensions=embedding_dimensions,
        )
    )

    # Check summarization provider
    try:
        _ = ProviderRegistry.get_summarization_provider(settings.summarization)
        summarization_status = "healthy"
        summarization_message = None
    except Exception as e:
        summarization_status = "unavailable"
        summarization_message = str(e)

    providers.append(
        ProviderHealth(
            provider_type="summarization",
            provider_name=str(settings.summarization.provider),
            model=settings.summarization.model,
            status=summarization_status,
            message=summarization_message,
        )
    )

    # Check reranker provider if reranking is enabled
    from brainpalace_server.config import settings as app_settings

    if app_settings.ENABLE_RERANKING:
        try:
            _ = ProviderRegistry.get_reranker_provider(settings.reranker)
            reranker_status = "healthy"
            reranker_message = None
        except Exception as e:
            reranker_status = "unavailable"
            reranker_message = str(e)

        providers.append(
            ProviderHealth(
                provider_type="reranker",
                provider_name=str(settings.reranker.provider),
                model=settings.reranker.model,
                status=reranker_status,
                message=reranker_message,
            )
        )

    return ProvidersStatus(
        config_source=config_source,
        strict_mode=strict_mode,
        validation_errors=error_messages,
        providers=providers,
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/postgres",
    summary="PostgreSQL Health",
    description=(
        "Returns PostgreSQL connection pool metrics and database info. "
        "Only available when storage backend is 'postgres'."
    ),
)
async def postgres_health(request: Request) -> dict[str, Any]:
    """Check PostgreSQL backend health and pool metrics.

    Returns pool status (pool_size, checked_in, checked_out, overflow)
    and database connection info when the backend is PostgreSQL.

    Returns:
        Dictionary with pool metrics and database info.

    Raises:
        HTTPException: If backend is not postgres (400).
    """
    backend_type = get_effective_backend_type()
    if backend_type != "postgres":
        raise HTTPException(
            status_code=400,
            detail=(
                "PostgreSQL health endpoint only available when "
                "storage backend is 'postgres'"
            ),
        )

    try:
        backend = request.app.state.storage_backend
        pool_metrics = await backend.connection_manager.get_pool_status()

        # Try a test query for database version
        from sqlalchemy import text as sa_text

        db_info: dict[str, Any] = {}
        try:
            async with backend.connection_manager.engine.connect() as conn:
                result = await conn.execute(sa_text("SELECT version()"))
                row = result.fetchone()
                if row:
                    db_info["version"] = row[0]
        except Exception:
            db_info["version"] = "unavailable"

        db_info["host"] = backend.config.host
        db_info["port"] = backend.config.port
        db_info["database"] = backend.config.database

        return {
            "status": "healthy",
            "backend": "postgres",
            "pool": pool_metrics,
            "database": db_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("PostgreSQL health check failed: %s", e)
        return {
            "status": "unhealthy",
            "backend": "postgres",
            "error": str(e),
        }
