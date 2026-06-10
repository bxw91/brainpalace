"""Embedding price lookup (dashboard plan 04)."""

from brainpalace_server.services.pricing import lookup_embedding_price


def test_known_openai_model():
    assert lookup_embedding_price("openai", "text-embedding-3-small") == 0.02


def test_lookup_is_case_insensitive():
    assert lookup_embedding_price("OpenAI", "Text-Embedding-3-Large") == 0.13


def test_unknown_model_returns_none():
    assert lookup_embedding_price("ollama", "nomic-embed-text") is None
