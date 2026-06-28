"""Embedding generation using pluggable providers.

This module provides embedding functionality using the configurable
provider system. Providers are selected based on config.yaml or
environment defaults.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Optional

from brainpalace_server.config.provider_config import load_provider_settings
from brainpalace_server.providers.factory import ProviderRegistry

if TYPE_CHECKING:
    from brainpalace_server.providers.base import EmbeddingProvider

from .chunking import TextChunk

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Generates embeddings using pluggable providers.

    Supports batch processing with configurable batch sizes
    and automatic provider selection based on configuration.
    """

    def __init__(
        self,
        embedding_provider: Optional["EmbeddingProvider"] = None,
    ):
        """Initialize the embedding generator.

        Args:
            embedding_provider: Optional embedding provider. If not provided,
                creates one from configuration.
        """
        # Load configuration
        self._settings = load_provider_settings()

        # Initialize providers from config or use provided ones
        if embedding_provider is not None:
            self._embedding_provider = embedding_provider
        else:
            self._embedding_provider = ProviderRegistry.get_embedding_provider(
                self._settings.embedding
            )

        logger.info(
            f"EmbeddingGenerator initialized with "
            f"{self._embedding_provider.provider_name} embeddings "
            f"({self._embedding_provider.model_name})"
        )

    @property
    def model(self) -> str:
        """Get the embedding model name."""
        return self._embedding_provider.model_name

    @property
    def embedding_provider(self) -> "EmbeddingProvider":
        """Get the embedding provider."""
        return self._embedding_provider

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text (cache-intercepted).

        Checks the embedding cache before calling the provider. On a cache
        miss, calls the provider and stores the result for future requests.
        If the cache is not initialised, delegates directly to the provider
        for backward compatibility.

        Lazy-imports the cache module to avoid a circular import between
        ``indexing`` and ``services`` packages (both loaded at startup).

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        # Lazy import to avoid circular import at module init time:
        #   indexing.__init__ -> embedding -> services.embedding_cache ->
        #   services.__init__ -> indexing_service -> indexing.__init__
        from brainpalace_server.services.embedding_cache import (  # noqa: PLC0415
            EmbeddingCacheService,
            get_embedding_cache,
        )

        cache = get_embedding_cache()
        if cache is not None:
            key = EmbeddingCacheService.make_cache_key(
                text,
                self._embedding_provider.provider_name,
                self._embedding_provider.model_name,
                self._embedding_provider.get_dimensions(),
            )
            cached = await cache.get(key)
            if cached is not None:
                return cached
            result = await self._embedding_provider.embed_text(text)
            await cache.put(key, result)
            return result
        return await self._embedding_provider.embed_text(text)

    async def embed_texts(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts (batch cache-intercepted).

        Performs a batch cache lookup for all texts, then calls the provider
        only for cache misses. Results are stored in the cache before
        returning. Order is preserved in the output list.

        If the cache is not initialised, delegates directly to the provider
        for backward compatibility.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed, total) for
                progress reporting. Passed only to the provider call for
                miss texts.

        Returns:
            List of embedding vectors in the same order as ``texts``.
        """
        # Lazy import to break circular import (see embed_text for details)
        from brainpalace_server.services.embedding_cache import (  # noqa: PLC0415
            EmbeddingCacheService,
            get_embedding_cache,
        )

        cache = get_embedding_cache()
        if cache is None:
            from brainpalace_server.services.usage_metrics import (  # noqa: PLC0415
                current_usage_source,
                record_usage,
            )

            embeddings, usage = await self._embedding_provider.embed_texts_with_usage(
                texts, progress_callback
            )
            record_usage(
                "embedding",
                self._embedding_provider.provider_name,
                self._embedding_provider.model_name,
                current_usage_source(),
                chunks=len(texts),
                calls=1,
                tokens_in=usage.tokens_in,
                cache_read=usage.cache_read,
            )
            return embeddings

        dims = self._embedding_provider.get_dimensions()
        provider = self._embedding_provider.provider_name
        model = self._embedding_provider.model_name

        # Build cache keys for all texts
        keys = [
            EmbeddingCacheService.make_cache_key(t, provider, model, dims)
            for t in texts
        ]

        # Batch lookup: one SQL query for all keys
        hits = await cache.get_batch(keys)

        # Assemble results list; identify miss indices
        results: list[list[float] | None] = [hits.get(k) for k in keys]
        miss_indices = [i for i, r in enumerate(results) if r is None]

        if miss_indices:
            from brainpalace_server.services.usage_metrics import (  # noqa: PLC0415
                current_usage_source,
                record_usage,
            )

            miss_texts = [texts[i] for i in miss_indices]
            (
                miss_embeddings,
                usage,
            ) = await self._embedding_provider.embed_texts_with_usage(
                miss_texts, progress_callback
            )
            # Meter only the misses — local-cache hits did no provider work, so
            # they record nothing ("work in window", §6-F8). usage.cache_read is
            # the provider-side prompt cache, distinct from our embedding cache.
            record_usage(
                "embedding",
                provider,
                model,
                current_usage_source(),
                chunks=len(miss_texts),
                calls=1,
                tokens_in=usage.tokens_in,
                cache_read=usage.cache_read,
            )
            # Collect results and batch-write to cache in one transaction
            cache_items: list[tuple[str, list[float]]] = []
            for idx, embedding in zip(miss_indices, miss_embeddings, strict=True):
                results[idx] = embedding
                cache_items.append((keys[idx], embedding))
            await cache.put_many(cache_items)

        # All results are now populated (no Nones remain)
        return [r for r in results if r is not None]

    async def uncached_indices(self, texts: list[str]) -> list[int]:
        """Indices of ``texts`` whose embeddings are NOT in the cache.

        Used by the per-job token budget so it counts only the texts that
        would actually hit the provider — cached texts cost nothing. The probe
        is conservative: with no cache configured, or on any lookup error,
        every index is returned (the budget then guards everything, exactly
        the pre-cache behavior). Read-only; never raises.
        """
        if not texts:
            return []
        # Lazy import to break circular import (see embed_text for details)
        from brainpalace_server.services.embedding_cache import (  # noqa: PLC0415
            EmbeddingCacheService,
            get_embedding_cache,
        )

        cache = get_embedding_cache()
        if cache is None:
            return list(range(len(texts)))
        try:
            dims = self._embedding_provider.get_dimensions()
            provider = self._embedding_provider.provider_name
            model = self._embedding_provider.model_name
            keys = [
                EmbeddingCacheService.make_cache_key(t, provider, model, dims)
                for t in texts
            ]
            hits = await cache.get_batch(keys)
            return [i for i, k in enumerate(keys) if k not in hits]
        except Exception as exc:  # noqa: BLE001 — probe must never break indexing
            logger.warning(
                "Cache-miss probe failed (%s) — budgeting all %d texts",
                exc,
                len(texts),
            )
            return list(range(len(texts)))

    async def embed_chunks(
        self,
        chunks: list[TextChunk],
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a list of text chunks.

        Args:
            chunks: List of TextChunk objects.
            progress_callback: Optional callback for progress updates.

        Returns:
            List of embedding vectors corresponding to each chunk.
        """
        texts = [chunk.text for chunk in chunks]
        return await self.embed_texts(texts, progress_callback)

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query.

        This is a convenience wrapper around embed_text for queries.

        Args:
            query: The search query text.

        Returns:
            Query embedding vector.
        """
        return await self.embed_text(query)

    def get_embedding_dimensions(self) -> int:
        """Get the expected embedding dimensions for the current model.

        Returns:
            Number of dimensions in the embedding vector.
        """
        return self._embedding_provider.get_dimensions()


# Singleton instance
_embedding_generator: EmbeddingGenerator | None = None


def get_embedding_generator() -> EmbeddingGenerator:
    """Get the global embedding generator instance."""
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator()
    return _embedding_generator


def reset_embedding_generator() -> None:
    """Reset the global embedding generator (for testing)."""
    global _embedding_generator
    _embedding_generator = None
