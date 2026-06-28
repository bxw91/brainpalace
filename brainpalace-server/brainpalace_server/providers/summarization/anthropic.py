"""Anthropic (Claude) summarization provider implementation."""

import logging
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from brainpalace_server.providers.base import BaseSummarizationProvider, Usage
from brainpalace_server.providers.exceptions import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from brainpalace_server.config.provider_config import SummarizationConfig

logger = logging.getLogger(__name__)


class AnthropicSummarizationProvider(BaseSummarizationProvider):
    """Anthropic (Claude) summarization provider.

    Supports:
    - claude-haiku-4-5-20251001 (fast, cost-effective)
    - claude-sonnet-4-5-20250514 (balanced)
    - claude-opus-4-5-20251101 (highest quality)
    - And other Claude models
    """

    def __init__(self, config: "SummarizationConfig") -> None:
        """Initialize Anthropic summarization provider.

        Args:
            config: Summarization configuration

        Raises:
            AuthenticationError: If API key is not available
        """
        api_key = config.get_api_key()
        if not api_key:
            raise AuthenticationError(
                "Missing API key. Set "
                f"{config.resolved_api_key_env()} environment variable.",
                self.provider_name,
            )

        max_tokens = config.params.get("max_tokens", 300)
        temperature = config.params.get("temperature", 0.1)
        prompt_template = config.params.get("prompt_template")

        super().__init__(
            model=config.model,
            max_tokens=max_tokens,
            temperature=temperature,
            prompt_template=prompt_template,
        )

        self._client = AsyncAnthropic(api_key=api_key)

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return "Anthropic"

    async def generate(self, prompt: str) -> str:
        """Generate text based on prompt using Claude.

        Args:
            prompt: The prompt to send to Claude

        Returns:
            Generated text response

        Raises:
            ProviderError: If generation fails
        """
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            # Extract text from response
            return response.content[0].text  # type: ignore[union-attr]
        except Exception as e:
            raise ProviderError(
                f"Failed to generate text: {e}",
                self.provider_name,
                cause=e,
            ) from e

    async def generate_with_usage(self, prompt: str) -> tuple[str, Usage]:
        """Generate text and return Anthropic token usage by value (§6-F3).

        Reads input_tokens, output_tokens, cache_read_input_tokens, and
        cache_creation_input_tokens from the SDK response usage block.
        Uses getattr(..., 0) or 0 for every field so absent fields → 0 (truthful).
        """
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            u = getattr(response, "usage", None)
            usage = (
                Usage(
                    tokens_in=int(getattr(u, "input_tokens", 0) or 0),
                    tokens_out=int(getattr(u, "output_tokens", 0) or 0),
                    cache_read=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                    cache_write=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                )
                if u is not None
                else Usage()
            )
            return response.content[0].text, usage  # type: ignore[union-attr]
        except Exception as e:
            raise ProviderError(
                f"Failed to generate text: {e}",
                self.provider_name,
                cause=e,
            ) from e
