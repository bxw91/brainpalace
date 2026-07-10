"""Pins the runtime contract for a missing embedding key (spec Item 1
runtime guardrail): construction fails with a message naming the env var,
so any surface (job status, ingest endpoint) can show an actionable error."""

import pytest

from brainpalace_server.config.provider_config import EmbeddingConfig
from brainpalace_server.providers.embedding.openai import OpenAIEmbeddingProvider
from brainpalace_server.providers.exceptions import ProviderError


def test_missing_openai_key_names_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = EmbeddingConfig(provider="openai")  # no key anywhere
    with pytest.raises(ProviderError) as exc:
        OpenAIEmbeddingProvider(cfg)
    assert "OPENAI_API_KEY" in str(exc.value)
