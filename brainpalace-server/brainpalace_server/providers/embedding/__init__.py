"""Embedding providers for BrainPalace.

This module provides embedding implementations for:
- OpenAI (text-embedding-3-large, text-embedding-3-small, text-embedding-ada-002)
- Ollama (nomic-embed-text, mxbai-embed-large, etc.)
- Cohere (embed-english-v3, embed-multilingual-v3, etc.)
"""

from brainpalace_server.providers.embedding.cohere import CohereEmbeddingProvider
from brainpalace_server.providers.embedding.ollama import OllamaEmbeddingProvider
from brainpalace_server.providers.embedding.openai import OpenAIEmbeddingProvider
from brainpalace_server.providers.factory import ProviderRegistry

# Register embedding providers
ProviderRegistry.register_embedding_provider("openai", OpenAIEmbeddingProvider)
ProviderRegistry.register_embedding_provider("ollama", OllamaEmbeddingProvider)
ProviderRegistry.register_embedding_provider("cohere", CohereEmbeddingProvider)

__all__ = [
    "OpenAIEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "CohereEmbeddingProvider",
]
