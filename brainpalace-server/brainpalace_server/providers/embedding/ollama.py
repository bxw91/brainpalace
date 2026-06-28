"""Ollama embedding provider implementation."""

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from openai import AsyncOpenAI

from brainpalace_server.providers.base import BaseEmbeddingProvider, Usage
from brainpalace_server.providers.exceptions import (
    OllamaConnectionError,
    ProviderError,
)

if TYPE_CHECKING:
    from brainpalace_server.config.provider_config import EmbeddingConfig

logger = logging.getLogger(__name__)

# Bound each request so a stalled local server can't wedge an index job on the
# SDK's 600s default read timeout. Higher than cloud defaults since local models
# can be slow. Overridable via config.params {"timeout"}.
DEFAULT_REQUEST_TIMEOUT = 120.0

# Model dimension mappings for common Ollama embedding models
OLLAMA_MODEL_DIMENSIONS: dict[str, int] = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
    "bge-m3": 1024,
    "bge-large": 1024,
}

DEFAULT_OLLAMA_DIMENSIONS = 768


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Ollama embedding provider using local models.

    Uses OpenAI-compatible API endpoint provided by Ollama.

    Supports:
    - nomic-embed-text (768 dimensions, general purpose)
    - mxbai-embed-large (1024 dimensions, multilingual)
    - all-minilm (384 dimensions, lightweight)
    - snowflake-arctic-embed (1024 dimensions, high quality)
    - And any other embedding model available in Ollama
    """

    def __init__(self, config: "EmbeddingConfig") -> None:
        """Initialize Ollama embedding provider.

        Args:
            config: Embedding configuration

        Note:
            Ollama does not require an API key as it runs locally.
        """
        batch_size = config.params.get("batch_size", 10)
        super().__init__(model=config.model, batch_size=batch_size)

        # Ollama uses OpenAI-compatible API
        base_url = config.get_base_url() or "http://localhost:11434/v1"
        self._base_url = base_url
        self._client = AsyncOpenAI(
            api_key="ollama",  # Ollama doesn't need real key
            base_url=base_url,
            timeout=config.params.get("timeout", DEFAULT_REQUEST_TIMEOUT),
        )

        # Optional parameters
        self._num_ctx = config.params.get("num_ctx", 2048)
        self._num_threads = config.params.get("num_threads")
        self._request_delay_ms: int = int(config.params.get("request_delay_ms", 0))
        self._max_retries: int = int(config.params.get("max_retries", 3))

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return "Ollama"

    def get_dimensions(self) -> int:
        """Get embedding dimensions for current model.

        Returns:
            Number of dimensions in embedding vector
        """
        return OLLAMA_MODEL_DIMENSIONS.get(self._model, DEFAULT_OLLAMA_DIMENSIONS)

    def _is_retryable_error(self, exc: Exception) -> bool:
        """Return True when the exception should be retried."""
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return True
        if isinstance(exc, httpx.ReadTimeout):
            return True
        if isinstance(exc, httpx.RemoteProtocolError):
            return True
        if isinstance(exc, httpx.ConnectError):
            return "refused" not in str(exc).lower()
        return False

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            OllamaConnectionError: If Ollama is not running
            ProviderError: If embedding generation fails
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=text,
                )
                result = response.data[0].embedding
                if self._request_delay_ms > 0:
                    await asyncio.sleep(self._request_delay_ms / 1000)
                return result
            except Exception as e:
                if isinstance(e, ConnectionRefusedError):
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if isinstance(e, httpx.ConnectError) and "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "connection" in str(e).lower() or "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "model not found" in str(e).lower():
                    raise ProviderError(
                        f"Failed to generate embedding: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e
                if not self._is_retryable_error(e):
                    raise ProviderError(
                        f"Failed to generate embedding: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e

                last_exc = e
                if attempt < self._max_retries:
                    delay = min(2**attempt, 30)
                    logger.warning(
                        "Retryable error in embed_text "
                        f"(attempt {attempt + 1}/{self._max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)

        raise ProviderError(
            "Failed to generate embedding after "
            f"{self._max_retries} retries: {last_exc}",
            self.provider_name,
            cause=last_exc,
        ) from last_exc

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors

        Raises:
            OllamaConnectionError: If Ollama is not running
            ProviderError: If embedding generation fails
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                )
                result = [item.embedding for item in response.data]
                if self._request_delay_ms > 0:
                    await asyncio.sleep(self._request_delay_ms / 1000)
                return result
            except Exception as e:
                if isinstance(e, ConnectionRefusedError):
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if isinstance(e, httpx.ConnectError) and "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "connection" in str(e).lower() or "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "model not found" in str(e).lower():
                    raise ProviderError(
                        f"Failed to generate batch embeddings: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e
                if not self._is_retryable_error(e):
                    raise ProviderError(
                        f"Failed to generate batch embeddings: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e

                last_exc = e
                if attempt < self._max_retries:
                    delay = min(2**attempt, 30)
                    logger.warning(
                        "Retryable error in _embed_batch "
                        f"(attempt {attempt + 1}/{self._max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)

        raise ProviderError(
            "Failed to generate batch embeddings after "
            f"{self._max_retries} retries: {last_exc}",
            self.provider_name,
            cause=last_exc,
        ) from last_exc

    async def _embed_batch_with_usage(
        self, texts: list[str]
    ) -> tuple[list[list[float]], Usage]:
        """Batch embed returning Ollama token usage by value (§6-F3).

        Ollama's embedding provider uses the OpenAI-compatible API (AsyncOpenAI),
        so the response has OpenAI-shaped usage fields (prompt_tokens), not the
        native Ollama REST field (prompt_eval_count). This is a known divergence
        from the plan's mapping table — real code takes precedence.
        Uses getattr(..., 0) or 0 everywhere so absent fields → 0 (truthful).
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=texts,
                )
                result = [item.embedding for item in response.data]
                u = getattr(response, "usage", None)
                usage = (
                    Usage(
                        tokens_in=int(getattr(u, "prompt_tokens", 0) or 0),
                        tokens_out=0,
                        cache_read=0,
                        cache_write=0,
                    )
                    if u is not None
                    else Usage()
                )
                if self._request_delay_ms > 0:
                    await asyncio.sleep(self._request_delay_ms / 1000)
                return result, usage
            except Exception as e:
                if isinstance(e, ConnectionRefusedError):
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if isinstance(e, httpx.ConnectError) and "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "connection" in str(e).lower() or "refused" in str(e).lower():
                    raise OllamaConnectionError(self._base_url, cause=e) from e
                if "model not found" in str(e).lower():
                    raise ProviderError(
                        f"Failed to generate batch embeddings: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e
                if not self._is_retryable_error(e):
                    raise ProviderError(
                        f"Failed to generate batch embeddings: {e}",
                        self.provider_name,
                        cause=e,
                    ) from e

                last_exc = e
                if attempt < self._max_retries:
                    delay = min(2**attempt, 30)
                    logger.warning(
                        "Retryable error in _embed_batch_with_usage "
                        f"(attempt {attempt + 1}/{self._max_retries}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)

        raise ProviderError(
            "Failed to generate batch embeddings after "
            f"{self._max_retries} retries: {last_exc}",
            self.provider_name,
            cause=last_exc,
        ) from last_exc

    async def health_check(self) -> bool:
        """Check if Ollama is running and accessible.

        Returns:
            True if Ollama is healthy, False otherwise
        """
        try:
            # Try to list models to verify connection
            await self._client.models.list()
            return True
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False
