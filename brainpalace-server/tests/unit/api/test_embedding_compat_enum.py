"""Regression: check_embedding_compatibility must not false-positive when the
config provider is the (str, Enum) ``EmbeddingProviderType`` and the stored
metadata holds the enum *value*.

Before the fix, current_provider was computed as ``str(enum)`` →
"EmbeddingProviderType.OPENAI", which never equals the stored "openai", so every
query 409'd with a bogus "Embedding provider mismatch" even on an unchanged config.
"""

from types import SimpleNamespace

import pytest

from brainpalace_server.api import main
from brainpalace_server.providers.base import EmbeddingProviderType
from brainpalace_server.storage.vector_store import EmbeddingMetadata


class _FakeVectorStore:
    def __init__(self, metadata: EmbeddingMetadata | None) -> None:
        self._metadata = metadata

    async def get_embedding_metadata(self) -> EmbeddingMetadata | None:
        return self._metadata


@pytest.mark.asyncio
async def test_enum_provider_matches_stored_value_no_warning(monkeypatch) -> None:
    """Enum-typed config provider + matching stored value → no mismatch."""
    stored = EmbeddingMetadata("openai", "text-embedding-3-large", 3072)
    settings = SimpleNamespace(
        embedding=SimpleNamespace(
            provider=EmbeddingProviderType.OPENAI,  # the real enum, not a str
            model="text-embedding-3-large",
        )
    )
    monkeypatch.setattr(main, "load_provider_settings", lambda: settings)
    monkeypatch.setattr(
        "brainpalace_server.providers.factory.ProviderRegistry.get_embedding_provider",
        lambda cfg: SimpleNamespace(get_dimensions=lambda: 3072),
    )

    warning = await main.check_embedding_compatibility(_FakeVectorStore(stored))

    assert warning is None


@pytest.mark.asyncio
async def test_real_provider_change_still_warns(monkeypatch) -> None:
    """A genuine provider change is still reported (fix doesn't mask real drift)."""
    stored = EmbeddingMetadata("openai", "text-embedding-3-large", 3072)
    settings = SimpleNamespace(
        embedding=SimpleNamespace(
            provider=EmbeddingProviderType.COHERE,
            model="embed-english-v3.0",
        )
    )
    monkeypatch.setattr(main, "load_provider_settings", lambda: settings)
    monkeypatch.setattr(
        "brainpalace_server.providers.factory.ProviderRegistry.get_embedding_provider",
        lambda cfg: SimpleNamespace(get_dimensions=lambda: 1024),
    )

    warning = await main.check_embedding_compatibility(_FakeVectorStore(stored))

    assert warning is not None
    assert "cohere" in warning
    assert "EmbeddingProviderType" not in warning  # value, not enum repr
