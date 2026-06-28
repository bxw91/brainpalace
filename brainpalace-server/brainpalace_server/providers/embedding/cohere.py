"""Cohere embedding provider implementation."""

import logging
from typing import TYPE_CHECKING

import cohere

from brainpalace_server.providers.base import BaseEmbeddingProvider, Usage
from brainpalace_server.providers.exceptions import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from brainpalace_server.config.provider_config import EmbeddingConfig

logger = logging.getLogger(__name__)

# Model dimension mappings for Cohere embedding models
COHERE_MODEL_DIMENSIONS: dict[str, int] = {
    "embed-english-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-v3.0": 1024,
    "embed-multilingual-light-v3.0": 384,
    "embed-english-v2.0": 4096,
    "embed-english-light-v2.0": 1024,
    "embed-multilingual-v2.0": 768,
}

DEFAULT_COHERE_DIMENSIONS = 1024


class CohereEmbeddingProvider(BaseEmbeddingProvider):
    """Cohere embedding provider using Cohere's embedding models.

    Supports:
    - embed-english-v3.0 (1024 dimensions, best for English)
    - embed-english-light-v3.0 (384 dimensions, faster)
    - embed-multilingual-v3.0 (1024 dimensions, 100+ languages)
    - embed-multilingual-light-v3.0 (384 dimensions, faster multilingual)

    Cohere embeddings support different input types for optimal performance:
    - search_document: For indexing documents to be searched
    - search_query: For search queries
    - classification: For classification tasks
    - clustering: For clustering tasks
    """

    def __init__(self, config: "EmbeddingConfig") -> None:
        """Initialize Cohere embedding provider.

        Args:
            config: Embedding configuration

        Raises:
            AuthenticationError: If API key is not available
        """
        api_key = config.get_api_key()
        if not api_key:
            raise AuthenticationError(
                "Missing API key. Set "
                f"{config.resolved_api_key_env()} environment variable.",
                self.provider_name,
            )

        batch_size = config.params.get("batch_size", 96)  # Cohere limit
        super().__init__(model=config.model, batch_size=batch_size)

        self._client = cohere.AsyncClientV2(api_key=api_key)
        self._input_type = config.params.get("input_type", "search_document")
        self._truncate = config.params.get("truncate", "END")

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return "Cohere"

    def get_dimensions(self) -> int:
        """Get embedding dimensions for current model.

        Returns:
            Number of dimensions in embedding vector
        """
        return COHERE_MODEL_DIMENSIONS.get(self._model, DEFAULT_COHERE_DIMENSIONS)

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            ProviderError: If embedding generation fails
        """
        try:
            response = await self._client.embed(
                texts=[text],
                model=self._model,
                input_type=self._input_type,
                truncate=self._truncate,
            )
            embeddings = response.embeddings.float_
            if embeddings is None:
                raise ProviderError(
                    "No embeddings returned from Cohere",
                    self.provider_name,
                )
            return list(embeddings[0])
        except Exception as e:
            raise ProviderError(
                f"Failed to generate embedding: {e}",
                self.provider_name,
                cause=e,
            ) from e

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors

        Raises:
            ProviderError: If embedding generation fails
        """
        try:
            response = await self._client.embed(
                texts=texts,
                model=self._model,
                input_type=self._input_type,
                truncate=self._truncate,
            )
            embeddings = response.embeddings.float_
            if embeddings is None:
                raise ProviderError(
                    "No embeddings returned from Cohere",
                    self.provider_name,
                )
            return [list(emb) for emb in embeddings]
        except Exception as e:
            raise ProviderError(
                f"Failed to generate batch embeddings: {e}",
                self.provider_name,
                cause=e,
            ) from e

    async def _embed_batch_with_usage(
        self, texts: list[str]
    ) -> tuple[list[list[float]], Usage]:
        """Batch embed returning Cohere billed token usage by value (§6-F3).

        Reads response.meta.billed_units.input_tokens.
        Uses getattr(..., 0) or 0 everywhere so absent fields → 0 (truthful).
        """
        try:
            response = await self._client.embed(
                texts=texts,
                model=self._model,
                input_type=self._input_type,
                truncate=self._truncate,
            )
            embeddings = response.embeddings.float_
            if embeddings is None:
                raise ProviderError(
                    "No embeddings returned from Cohere",
                    self.provider_name,
                )
            meta = getattr(response, "meta", None)
            billed = getattr(meta, "billed_units", None) if meta is not None else None
            usage = Usage(
                tokens_in=int(getattr(billed, "input_tokens", 0) or 0),
                tokens_out=0,
                cache_read=0,
                cache_write=0,
            )
            return [list(emb) for emb in embeddings], usage
        except Exception as e:
            raise ProviderError(
                f"Failed to generate batch embeddings: {e}",
                self.provider_name,
                cause=e,
            ) from e

    def set_input_type(self, input_type: str) -> None:
        """Set the input type for embeddings.

        Args:
            input_type: One of 'search_document', 'search_query',
                       'classification', or 'clustering'
        """
        valid_types = [
            "search_document",
            "search_query",
            "classification",
            "clustering",
        ]
        if input_type not in valid_types:
            raise ValueError(f"Invalid input_type. Must be one of: {valid_types}")
        self._input_type = input_type
