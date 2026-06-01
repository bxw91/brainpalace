"""Regression: EmbeddingGenerator must not build the summarization provider at
construction time.

Building it eagerly made the whole server fail to start when the summarization
provider's API key was missing (e.g. default summarization=anthropic with only
OPENAI_API_KEY set), even though embeddings / document indexing / session memory
only need the embedding provider. The summarization provider is now built lazily
on first summary, and summary generation already degrades to docstring
extraction on error.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from brainpalace_server.indexing.embedding import EmbeddingGenerator


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding=SimpleNamespace(provider="openai", model="text-embedding-3-large"),
        summarization=SimpleNamespace(provider="anthropic", model="claude-haiku"),
    )


def _embedding_provider() -> MagicMock:
    prov = MagicMock()
    prov.provider_name = "OpenAI"
    prov.model_name = "text-embedding-3-large"
    return prov


def test_init_does_not_build_summarization_provider() -> None:
    """Construction must not touch the summarization provider (no key crash)."""
    with (
        patch(
            "brainpalace_server.indexing.embedding.load_provider_settings",
            return_value=_settings(),
        ),
        patch(
            "brainpalace_server.indexing.embedding.ProviderRegistry."
            "get_embedding_provider",
            return_value=_embedding_provider(),
        ),
        patch(
            "brainpalace_server.indexing.embedding.ProviderRegistry."
            "get_summarization_provider",
        ) as mock_get_summary,
    ):
        gen = EmbeddingGenerator()
        # Eager init would have called this — it must not be touched yet.
        mock_get_summary.assert_not_called()
        assert gen._summarization_provider is None


@pytest.mark.asyncio
async def test_generate_summary_falls_back_when_summarizer_key_missing() -> None:
    """A missing summarization key surfaces only on use, and degrades to the
    docstring fallback instead of raising."""
    with (
        patch(
            "brainpalace_server.indexing.embedding.load_provider_settings",
            return_value=_settings(),
        ),
        patch(
            "brainpalace_server.indexing.embedding.ProviderRegistry."
            "get_embedding_provider",
            return_value=_embedding_provider(),
        ),
        patch(
            "brainpalace_server.indexing.embedding.ProviderRegistry."
            "get_summarization_provider",
            side_effect=RuntimeError("Missing API key"),
        ) as mock_get_summary,
    ):
        gen = EmbeddingGenerator()
        code = '''def add(a, b):
    """Add two numbers and return the sum."""
    return a + b
'''
        # Must not raise; lazy build is attempted then caught -> fallback.
        summary = await gen.generate_summary(code)
        mock_get_summary.assert_called()  # built lazily on first use
        assert isinstance(summary, str)
