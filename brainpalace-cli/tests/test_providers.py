"""Tests for the canonical provider descriptor (brainpalace_cli.providers)."""

from __future__ import annotations

import json

from brainpalace_cli import config_schema as cs
from brainpalace_cli.providers import PROVIDERS, descriptor, recommended_model

# Conventional API-key env vars must mirror the server's provider-config map.
_EXPECTED_ENV = {
    ("embedding", "openai"): "OPENAI_API_KEY",
    ("embedding", "cohere"): "COHERE_API_KEY",
    ("embedding", "ollama"): None,
    ("summarization", "anthropic"): "ANTHROPIC_API_KEY",
    ("summarization", "openai"): "OPENAI_API_KEY",
    ("summarization", "gemini"): "GEMINI_API_KEY",
    ("summarization", "grok"): "XAI_API_KEY",
    ("summarization", "ollama"): None,
    ("reranker", "sentence-transformers"): None,
    ("reranker", "ollama"): None,
}

# Providers that talk to a custom/local endpoint need a base URL.
_EXPECTED_NEEDS_BASE_URL = {
    ("embedding", "ollama"),
    ("summarization", "ollama"),
    ("summarization", "grok"),
    ("reranker", "ollama"),
}


def test_kinds_present() -> None:
    assert set(PROVIDERS) == {"embedding", "summarization", "reranker"}


def test_providers_match_config_schema_valid_sets() -> None:
    """Every kind lists exactly the providers config_schema accepts."""
    assert set(PROVIDERS["embedding"]) == set(cs.VALID_EMBEDDING_PROVIDERS)
    assert set(PROVIDERS["summarization"]) == set(cs.VALID_SUMMARIZATION_PROVIDERS)
    assert set(PROVIDERS["reranker"]) == set(cs.VALID_RERANKER_PROVIDERS)


def test_every_provider_has_at_least_one_model() -> None:
    for kind, provs in PROVIDERS.items():
        for name, info in provs.items():
            assert info["models"], f"{kind}/{name} has no models"
            assert all(isinstance(m, str) and m for m in info["models"])


def test_default_api_key_env_is_sane() -> None:
    for (kind, name), expected in _EXPECTED_ENV.items():
        assert PROVIDERS[kind][name]["default_api_key_env"] == expected


def test_needs_base_url_correct() -> None:
    for kind, provs in PROVIDERS.items():
        for name, info in provs.items():
            expected = (kind, name) in _EXPECTED_NEEDS_BASE_URL
            assert info["needs_base_url"] is expected, f"{kind}/{name}"


def test_recommended_model_is_first() -> None:
    assert recommended_model("embedding", "openai") == "text-embedding-3-large"
    assert recommended_model("summarization", "anthropic") == (
        "claude-haiku-4-5-20251001"
    )
    assert recommended_model("reranker", "sentence-transformers") == (
        "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )
    assert recommended_model("embedding", "nope") is None


def test_no_stale_legacy_model_ids() -> None:
    """The stale dashboard presets (issue #7) must be gone everywhere."""
    all_models = {
        m
        for provs in PROVIDERS.values()
        for info in provs.values()
        for m in info["models"]
    }
    for stale in ("claude-3-5-haiku-latest", "claude-sonnet-4-6", "gpt-4o-mini"):
        assert stale not in all_models


def test_descriptor_is_json_serializable() -> None:
    d = descriptor()
    assert json.loads(json.dumps(d)) == d
    # Plain dicts (not TypedDict instances leaking shared references).
    assert d is not PROVIDERS
