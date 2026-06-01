"""Unit tests for provider configuration models."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

from brainpalace_server.config.provider_config import (
    EmbeddingConfig,
    ProviderSettings,
    SummarizationConfig,
    clear_settings_cache,
    load_provider_settings,
    validate_provider_config,
)
from brainpalace_server.providers.base import (
    EmbeddingProviderType,
    SummarizationProviderType,
)


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = EmbeddingConfig()
        assert config.provider == EmbeddingProviderType.OPENAI
        assert config.model == "text-embedding-3-large"
        # api_key_env defaults to None; resolved from provider on demand.
        assert config.api_key_env is None
        assert config.resolved_api_key_env() == "OPENAI_API_KEY"
        assert config.base_url is None
        assert config.params == {}

    def test_resolved_api_key_env_provider_derived(self) -> None:
        """Unset api_key_env resolves to the provider's conventional var."""
        assert EmbeddingConfig(provider="cohere").resolved_api_key_env() == (
            "COHERE_API_KEY"
        )
        assert EmbeddingConfig(provider="ollama").resolved_api_key_env() is None

    def test_resolved_api_key_env_explicit_wins(self) -> None:
        """Explicit api_key_env overrides provider derivation."""
        config = EmbeddingConfig(provider="cohere", api_key_env="MY_KEY")
        assert config.resolved_api_key_env() == "MY_KEY"

    def test_get_api_key_provider_derived_env(self) -> None:
        """Provider=cohere with no api_key_env reads COHERE_API_KEY."""
        with patch.dict(os.environ, {"COHERE_API_KEY": "cohere-secret"}):
            config = EmbeddingConfig(provider="cohere")
            assert config.get_api_key() == "cohere-secret"

    def test_provider_from_string(self) -> None:
        """Test provider enum conversion from string."""
        config = EmbeddingConfig(provider="ollama")
        assert config.provider == EmbeddingProviderType.OLLAMA

    def test_ollama_default_base_url(self) -> None:
        """Test Ollama gets default base URL."""
        config = EmbeddingConfig(provider="ollama")
        assert config.get_base_url() == "http://localhost:11434/v1"

    def test_custom_base_url(self) -> None:
        """Test custom base URL overrides default."""
        config = EmbeddingConfig(
            provider="ollama",
            base_url="http://custom:11434/v1",
        )
        assert config.get_base_url() == "http://custom:11434/v1"

    def test_get_api_key_from_env(self) -> None:
        """Test API key resolution from environment."""
        with patch.dict(os.environ, {"TEST_API_KEY": "test-key-value"}):
            config = EmbeddingConfig(api_key_env="TEST_API_KEY")
            assert config.get_api_key() == "test-key-value"

    def test_get_api_key_from_config_takes_precedence(self) -> None:
        """Test API key from config takes precedence over env var."""
        with patch.dict(os.environ, {"TEST_API_KEY": "env-key"}):
            config = EmbeddingConfig(api_key="config-key", api_key_env="TEST_API_KEY")
            assert config.get_api_key() == "config-key"

    def test_get_api_key_from_config_direct(self) -> None:
        """Test API key can be set directly in config."""
        config = EmbeddingConfig(api_key="direct-api-key")
        assert config.get_api_key() == "direct-api-key"

    def test_get_api_key_ollama_returns_none(self) -> None:
        """Test Ollama provider returns None for API key."""
        config = EmbeddingConfig(provider="ollama")
        assert config.get_api_key() is None

    def test_custom_params(self) -> None:
        """Test custom parameters are stored."""
        config = EmbeddingConfig(
            params={"batch_size": 50, "dimensions": 1024},
        )
        assert config.params["batch_size"] == 50
        assert config.params["dimensions"] == 1024


class TestSummarizationConfig:
    """Tests for SummarizationConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SummarizationConfig()
        assert config.provider == SummarizationProviderType.ANTHROPIC
        assert config.model == "claude-haiku-4-5-20251001"
        # api_key_env defaults to None; resolved from provider on demand.
        assert config.api_key_env is None
        assert config.resolved_api_key_env() == "ANTHROPIC_API_KEY"
        assert config.base_url is None
        assert config.params == {}

    def test_resolved_api_key_env_provider_derived(self) -> None:
        """Unset api_key_env resolves to the provider's conventional var."""
        assert SummarizationConfig(provider="openai").resolved_api_key_env() == (
            "OPENAI_API_KEY"
        )
        assert SummarizationConfig(provider="gemini").resolved_api_key_env() == (
            "GEMINI_API_KEY"
        )
        assert SummarizationConfig(provider="grok").resolved_api_key_env() == (
            "XAI_API_KEY"
        )
        assert SummarizationConfig(provider="ollama").resolved_api_key_env() is None

    def test_get_api_key_provider_derived_env(self) -> None:
        """Provider=openai with no api_key_env reads OPENAI_API_KEY (not Anthropic)."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-secret"}):
            config = SummarizationConfig(provider="openai")
            assert config.get_api_key() == "openai-secret"

    def test_provider_from_string(self) -> None:
        """Test provider enum conversion from string."""
        config = SummarizationConfig(provider="openai")
        assert config.provider == SummarizationProviderType.OPENAI

    def test_grok_default_base_url(self) -> None:
        """Test Grok gets default base URL."""
        config = SummarizationConfig(provider="grok")
        assert config.get_base_url() == "https://api.x.ai/v1"

    def test_ollama_default_base_url(self) -> None:
        """Test Ollama gets default base URL."""
        config = SummarizationConfig(provider="ollama")
        assert config.get_base_url() == "http://localhost:11434/v1"

    def test_get_api_key_from_env(self) -> None:
        """Test API key resolution from environment."""
        with patch.dict(os.environ, {"TEST_API_KEY": "test-key-value"}):
            config = SummarizationConfig(api_key_env="TEST_API_KEY")
            assert config.get_api_key() == "test-key-value"

    def test_get_api_key_from_config_takes_precedence(self) -> None:
        """Test API key from config takes precedence over env var."""
        with patch.dict(os.environ, {"TEST_API_KEY": "env-key"}):
            config = SummarizationConfig(
                api_key="config-key", api_key_env="TEST_API_KEY"
            )
            assert config.get_api_key() == "config-key"

    def test_get_api_key_from_config_direct(self) -> None:
        """Test API key can be set directly in config."""
        config = SummarizationConfig(api_key="direct-api-key")
        assert config.get_api_key() == "direct-api-key"

    def test_get_api_key_ollama_returns_none(self) -> None:
        """Test Ollama provider returns None for API key."""
        config = SummarizationConfig(provider="ollama")
        assert config.get_api_key() is None

    def test_custom_params(self) -> None:
        """Test custom parameters are stored."""
        config = SummarizationConfig(
            params={"max_tokens": 500, "temperature": 0.2},
        )
        assert config.params["max_tokens"] == 500
        assert config.params["temperature"] == 0.2


class TestProviderSettings:
    """Tests for ProviderSettings model."""

    def test_default_values(self) -> None:
        """Test default settings."""
        settings = ProviderSettings()
        assert settings.embedding.provider == EmbeddingProviderType.OPENAI
        assert settings.summarization.provider == SummarizationProviderType.ANTHROPIC

    def test_from_dict(self) -> None:
        """Test creation from dictionary (as from YAML)."""
        settings = ProviderSettings(
            embedding={
                "provider": "ollama",
                "model": "nomic-embed-text",
            },
            summarization={
                "provider": "openai",
                "model": "gpt-5",
            },
        )
        assert settings.embedding.provider == EmbeddingProviderType.OLLAMA
        assert settings.embedding.model == "nomic-embed-text"
        assert settings.summarization.provider == SummarizationProviderType.OPENAI
        assert settings.summarization.model == "gpt-5"


class TestValidateProviderConfig:
    """Tests for configuration validation."""

    def test_valid_ollama_config(self) -> None:
        """Test Ollama config doesn't require API keys."""
        settings = ProviderSettings(
            embedding={"provider": "ollama"},
            summarization={"provider": "ollama"},
        )
        errors = validate_provider_config(settings)
        assert errors == []

    def test_missing_embedding_api_key(self) -> None:
        """Test error when embedding API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            settings = ProviderSettings(
                embedding={"provider": "openai", "api_key_env": "MISSING_KEY"},
            )
            errors = validate_provider_config(settings)
            assert len(errors) >= 1
            assert "embedding" in str(errors[0]).lower() or "MISSING_KEY" in str(
                errors[0]
            )

    def test_missing_summarization_api_key(self) -> None:
        """Test error when summarization API key is missing."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True):
            settings = ProviderSettings(
                summarization={"provider": "anthropic", "api_key_env": "MISSING_KEY"},
            )
            errors = validate_provider_config(settings)
            assert len(errors) >= 1
            assert "summarization" in str(errors[0]).lower() or "MISSING_KEY" in str(
                errors[0]
            )

    def test_valid_config_with_keys(self) -> None:
        """Test valid config with all keys present."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "key1", "ANTHROPIC_API_KEY": "key2"},
        ):
            settings = ProviderSettings()
            errors = validate_provider_config(settings)
            assert errors == []


class TestLoadProviderSettings:
    """Tests for loading provider settings."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def test_default_when_no_config(self) -> None:
        """Test defaults are used when no config file exists."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "brainpalace_server.config.provider_config._find_config_file",
                return_value=None,
            ),
        ):
            settings = load_provider_settings()
            assert settings.embedding.provider == EmbeddingProviderType.OPENAI
            expected = SummarizationProviderType.ANTHROPIC
            assert settings.summarization.provider == expected


class TestGraphragSectionWarning:
    """A graphrag: section in config.yaml is parsed (Phase G, #126)."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_graphrag_section_logs_info(self, caplog) -> None:
        """A config.yaml with a graphrag: section logs an info message and parses it."""
        fake_path = Path("/fake/.brainpalace/config.yaml")
        with (
            patch(
                "brainpalace_server.config.provider_config._find_config_file",
                return_value=fake_path,
            ),
            patch(
                "brainpalace_server.config.provider_config._load_yaml_config",
                return_value={"graphrag": {"enabled": True}},
            ),
            caplog.at_level(logging.INFO),
        ):
            settings = load_provider_settings()
        assert settings.embedding.provider == EmbeddingProviderType.OPENAI
        assert "graphrag" in caplog.text.lower()
        assert "PROVIDER_CONFIGURATION.md" in caplog.text

    def test_config_without_graphrag_no_info(self, caplog) -> None:
        """A config.yaml without a graphrag: section logs no graphrag message."""
        fake_path = Path("/fake/.brainpalace/config.yaml")
        with (
            patch(
                "brainpalace_server.config.provider_config._find_config_file",
                return_value=fake_path,
            ),
            patch(
                "brainpalace_server.config.provider_config._load_yaml_config",
                return_value={"embedding": {"provider": "openai"}},
            ),
            caplog.at_level(logging.INFO),
        ):
            settings = load_provider_settings()
        assert settings.embedding.provider == EmbeddingProviderType.OPENAI
        assert "PROVIDER_CONFIGURATION.md" not in caplog.text
