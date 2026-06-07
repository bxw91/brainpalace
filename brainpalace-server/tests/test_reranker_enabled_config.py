"""Reranking is config-controllable and ON by default.

The query path gates on ``settings.ENABLE_RERANKING``; the server lifespan
reconciles that from ``reranker.enabled`` (default True) unless the
``ENABLE_RERANKING`` env var is set. Here we lock the config-model contract that
reconciliation relies on.
"""

from brainpalace_server.config.provider_config import RerankerConfig


def test_reranker_enabled_default_is_true() -> None:
    assert RerankerConfig().enabled is True


def test_reranker_enabled_round_trips() -> None:
    assert RerankerConfig(enabled=False).enabled is False
    # Parsed from a config dict (as load_provider_settings would).
    assert RerankerConfig(**{"enabled": False, "provider": "ollama"}).enabled is False
