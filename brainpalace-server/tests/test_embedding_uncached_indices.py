"""Regression: the per-job embedding token budget must count only cache misses.

The self-heal reindex of dropped files was blocked by BudgetExceededError
(~409K raw tokens vs a 300K budget) even though virtually every chunk was an
embedding-cache hit costing zero provider calls — so chunks the self-heal had
just dropped from the manifest never returned. ``EmbeddingGenerator.
uncached_indices`` reports which texts would actually hit the provider, and
the indexing pipeline budgets only those.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from brainpalace_server.indexing.embedding import EmbeddingGenerator
from brainpalace_server.services.embedding_cache import (
    EmbeddingCacheService,
    reset_embedding_cache,
    set_embedding_cache,
)

_PROVIDER = "OpenAI"
_MODEL = "text-embedding-3-large"
_DIMS = 8


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding=SimpleNamespace(provider="openai", model=_MODEL),
        summarization=SimpleNamespace(provider="anthropic", model="claude-haiku"),
    )


def _gen() -> EmbeddingGenerator:
    prov = MagicMock()
    prov.provider_name = _PROVIDER
    prov.model_name = _MODEL
    prov.get_dimensions.return_value = _DIMS
    with (
        patch(
            "brainpalace_server.indexing.embedding.load_provider_settings",
            return_value=_settings(),
        ),
        patch(
            "brainpalace_server.indexing.embedding.ProviderRegistry."
            "get_embedding_provider",
            return_value=prov,
        ),
    ):
        return EmbeddingGenerator()


class _StubCache:
    """Minimal cache double: batch lookup over a fixed hit-key set."""

    def __init__(self, hit_keys: set[str]) -> None:
        self._hits = hit_keys

    async def get_batch(self, cache_keys: list[str]) -> dict[str, list[float]]:
        return {k: [0.0] * _DIMS for k in cache_keys if k in self._hits}


class _BoomCache:
    async def get_batch(self, cache_keys: list[str]) -> dict[str, list[float]]:
        raise RuntimeError("database is locked")


@pytest.fixture(autouse=True)
def _clean_cache_singleton() -> Any:
    reset_embedding_cache()
    yield
    reset_embedding_cache()


@pytest.mark.asyncio
async def test_uncached_indices_excludes_cache_hits() -> None:
    hit_key = EmbeddingCacheService.make_cache_key("hit", _PROVIDER, _MODEL, _DIMS)
    set_embedding_cache(cast(Any, _StubCache({hit_key})))
    gen = _gen()
    assert await gen.uncached_indices(["hit", "miss", "hit"]) == [1]


@pytest.mark.asyncio
async def test_uncached_indices_without_cache_returns_all() -> None:
    gen = _gen()
    assert await gen.uncached_indices(["a", "b"]) == [0, 1]


@pytest.mark.asyncio
async def test_uncached_indices_empty_input() -> None:
    gen = _gen()
    assert await gen.uncached_indices([]) == []


@pytest.mark.asyncio
async def test_uncached_indices_probe_failure_is_conservative() -> None:
    """A cache-probe error must fall back to budgeting everything, never skip
    the guard."""
    set_embedding_cache(cast(Any, _BoomCache()))
    gen = _gen()
    assert await gen.uncached_indices(["a", "b"]) == [0, 1]
