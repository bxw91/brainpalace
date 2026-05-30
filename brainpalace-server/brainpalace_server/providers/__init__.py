"""Pluggable model providers for BrainPalace.

This package provides abstractions for embedding and summarization providers,
allowing configuration-driven selection between OpenAI, Ollama, Cohere (embeddings)
and Anthropic, OpenAI, Gemini, Grok, Ollama (summarization) providers.
"""

from brainpalace_server.providers.base import (
    BaseEmbeddingProvider,
    BaseSummarizationProvider,
    EmbeddingProvider,
    EmbeddingProviderType,
    SummarizationProvider,
    SummarizationProviderType,
)
from brainpalace_server.providers.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ModelNotFoundError,
    ProviderError,
    ProviderMismatchError,
    ProviderNotFoundError,
    RateLimitError,
)
from brainpalace_server.providers.factory import ProviderRegistry

__all__ = [
    # Protocols
    "EmbeddingProvider",
    "SummarizationProvider",
    # Base classes
    "BaseEmbeddingProvider",
    "BaseSummarizationProvider",
    # Enums
    "EmbeddingProviderType",
    "SummarizationProviderType",
    # Factory
    "ProviderRegistry",
    # Exceptions
    "ProviderError",
    "ConfigurationError",
    "AuthenticationError",
    "ProviderNotFoundError",
    "ProviderMismatchError",
    "RateLimitError",
    "ModelNotFoundError",
]


def _register_providers() -> None:
    """Register all built-in providers with the registry."""
    # Import providers to trigger registration
    from brainpalace_server.providers import (
        embedding,  # noqa: F401
        summarization,  # noqa: F401
    )

    # Silence unused import warnings
    _ = embedding
    _ = summarization


# Auto-register providers on import
_register_providers()
