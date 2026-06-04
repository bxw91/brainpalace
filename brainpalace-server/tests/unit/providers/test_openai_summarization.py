"""Unit tests for OpenAI (GPT) summarization provider."""

from unittest.mock import patch

import pytest

from brainpalace_server.config.provider_config import SummarizationConfig
from brainpalace_server.providers.exceptions import AuthenticationError
from brainpalace_server.providers.summarization.openai import (
    OpenAISummarizationProvider,
)


class TestOpenAISummarizationProvider:
    """Tests for OpenAISummarizationProvider."""

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_initialization(self) -> None:
        """Test provider initialization."""
        config = SummarizationConfig(provider="openai", model="gpt-5-mini")
        provider = OpenAISummarizationProvider(config)

        assert provider.provider_name == "OpenAI"

    def test_initialization_missing_key(self) -> None:
        """Test error when API key is missing."""
        with patch.dict("os.environ", {}, clear=True):
            config = SummarizationConfig(
                provider="openai",
                api_key_env="MISSING_KEY",
            )
            with pytest.raises(AuthenticationError):
                OpenAISummarizationProvider(config)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_client_has_bounded_timeout_by_default(self) -> None:
        """Client uses a bounded request timeout, not the SDK 600s default.

        Regression guard: per-code-chunk gpt-5-mini summarization calls are the
        index job's long pole; an unbounded 600s timeout on a dropped connection
        wedges the job on a half-dead socket and blocks cooperative cancel.
        """
        config = SummarizationConfig(provider="openai", model="gpt-5-mini")
        provider = OpenAISummarizationProvider(config)

        assert provider._client.timeout == 60.0
        assert provider._client.max_retries == 2

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_client_timeout_and_retries_overridable(self) -> None:
        """timeout / max_retries are overridable via config.params."""
        config = SummarizationConfig(
            provider="openai",
            model="gpt-5-mini",
            params={"timeout": 15.0, "max_retries": 5},
        )
        provider = OpenAISummarizationProvider(config)

        assert provider._client.timeout == 15.0
        assert provider._client.max_retries == 5
