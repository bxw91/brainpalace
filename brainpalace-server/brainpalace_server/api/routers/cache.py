"""Cache management API endpoints.

Provides endpoints for querying and clearing the embedding cache.
Mounted at ``/index/cache`` in the main application.

Endpoints:
    GET  / — Return combined hit/miss + disk statistics.
    DELETE / — Clear all cached embeddings and return freed counts.

Both GET and DELETE also accept requests without a trailing slash
so that clients hitting ``/index/cache`` (no slash) are served
directly instead of receiving a 307 redirect.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from brainpalace_server.config.provider_config import load_provider_settings
from brainpalace_server.services.embedding_cache import get_embedding_cache
from brainpalace_server.services.pricing import lookup_embedding_price

logger = logging.getLogger(__name__)

router = APIRouter()


async def _cache_status_impl(request: Request) -> dict[str, Any]:
    """Shared implementation for cache status (GET).

    Combines in-process session counters (hits, misses, hit_rate,
    mem_entries) with disk-level stats (entry_count, size_bytes) from
    SQLite.

    Returns:
        Dict with keys: hits, misses, hit_rate, mem_entries,
        entry_count, size_bytes.

    Raises:
        HTTPException: 503 if cache service is not initialised.
    """
    cache = get_embedding_cache()
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding cache service not initialised",
        )

    await cache.maybe_snapshot()

    stats = cache.get_stats()
    disk_stats = await cache.get_disk_stats()
    return {**stats, **disk_stats}


async def _clear_cache_impl(request: Request) -> dict[str, Any]:
    """Shared implementation for cache clear (DELETE).

    Counts entries and measures DB size before deletion, deletes all rows,
    runs VACUUM to reclaim disk space. In-memory LRU is also cleared.
    Session hit/miss counters are reset.

    Returns:
        Dict with keys: count (entries cleared), size_bytes,
        size_mb (size_bytes / 1 MB).

    Raises:
        HTTPException: 503 if cache service is not initialised.
    """
    cache = get_embedding_cache()
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding cache service not initialised",
        )

    count, size_bytes = await cache.clear()
    return {
        "count": count,
        "size_bytes": size_bytes,
        "size_mb": size_bytes / (1024 * 1024),
    }


# --- Canonical routes (with trailing slash) ---


@router.get(
    "/",
    summary="Embedding Cache Status",
    description=(
        "Returns embedding cache hit/miss counters and disk statistics. "
        "Returns 503 if the cache service is not initialised."
    ),
)
async def cache_status(request: Request) -> dict[str, Any]:
    """GET /index/cache/ — canonical."""
    return await _cache_status_impl(request)


@router.delete(
    "/",
    summary="Clear Embedding Cache",
    description=(
        "Deletes all cached embeddings and reclaims disk space via VACUUM. "
        "Returns the number of entries cleared and bytes freed. "
        "Safe to call while indexing jobs are running (running jobs will "
        "regenerate embeddings at normal API cost). "
        "Returns 503 if the cache service is not initialised."
    ),
)
async def clear_cache(request: Request) -> dict[str, Any]:
    """DELETE /index/cache/ — canonical."""
    return await _clear_cache_impl(request)


# --- Backward-compatible no-slash aliases ---
# Prevents 307 redirect when clients hit /index/cache without trailing slash.


@router.get(
    "",
    include_in_schema=False,
)
async def cache_status_no_slash(request: Request) -> dict[str, Any]:
    """GET /index/cache (no slash) — alias."""
    return await _cache_status_impl(request)


@router.delete(
    "",
    include_in_schema=False,
)
async def clear_cache_no_slash(request: Request) -> dict[str, Any]:
    """DELETE /index/cache (no slash) — alias."""
    return await _clear_cache_impl(request)


# --- History + economics (dashboard cost-&-cache panel) ---


@router.get(
    "/history",
    summary="Embedding Cache Hit-Rate History",
    description=(
        "Persisted hit/miss snapshots over time (oldest first). Reading this "
        "endpoint also writes an opportunistic snapshot, throttled to one per "
        "5 minutes. Returns 503 if the cache service is not initialised."
    ),
)
async def cache_history(
    request: Request, since: float | None = Query(None, ge=0)
) -> dict[str, Any]:
    """GET /index/cache/history — persisted hit-rate snapshots."""
    cache = get_embedding_cache()
    if cache is None:
        raise HTTPException(
            status_code=503, detail="Embedding cache service not initialised"
        )
    await cache.maybe_snapshot()
    return {"snapshots": await cache.get_stats_history(since)}


@router.get(
    "/economics",
    summary="Embedding Cost Estimate",
    description=(
        "ESTIMATED provider spend and cache savings: session hit/miss counters "
        "x avg_tokens x a static published price table. Null estimates when the "
        "provider/model has no known price (e.g. local providers). Returns 503 "
        "if the cache service is not initialised."
    ),
)
async def cache_economics(
    request: Request, avg_tokens: int = Query(400, ge=1, le=100_000)
) -> dict[str, Any]:
    """GET /index/cache/economics — estimated spend / savings."""
    cache = get_embedding_cache()
    if cache is None:
        raise HTTPException(
            status_code=503, detail="Embedding cache service not initialised"
        )
    stats = cache.get_stats()
    disk = await cache.get_disk_stats()
    provider_settings = load_provider_settings()
    _provider = provider_settings.embedding.provider
    provider = getattr(_provider, "value", str(_provider))
    model = str(provider_settings.embedding.model)
    price = lookup_embedding_price(provider, model)

    def cost(calls: int) -> float | None:
        if price is None:
            return None
        return round(calls * avg_tokens / 1_000_000 * price, 6)

    return {
        "provider": provider,
        "model": model,
        "price_usd_per_mtok": price,
        "avg_tokens_per_chunk": avg_tokens,
        "session_hits": stats["hits"],
        "session_misses": stats["misses"],
        "est_spend_usd": cost(stats["misses"]),
        "est_saved_usd": cost(stats["hits"]),
        "cached_entries": disk["entry_count"],
        "est_reindex_cost_usd": cost(disk["entry_count"]),
    }
