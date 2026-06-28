"""OpenAI (GPT) summarization provider implementation."""

import logging
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from brainpalace_server.providers.base import BaseSummarizationProvider, Usage
from brainpalace_server.providers.exceptions import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from brainpalace_server.config.provider_config import SummarizationConfig

logger = logging.getLogger(__name__)

# Bound each API request so a half-dead connection (e.g. a dropped link) can't
# wedge an index job on the SDK's 600s default read timeout. Overridable via
# config.params {"timeout", "max_retries"}.
DEFAULT_REQUEST_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2


class OpenAISummarizationProvider(BaseSummarizationProvider):
    """OpenAI (GPT) summarization provider.

    Supports:
    - gpt-5 (most capable)
    - gpt-5-mini (fast, cost-effective)
    - And other OpenAI chat models
    """

    def __init__(self, config: "SummarizationConfig") -> None:
        """Initialize OpenAI summarization provider.

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

        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=config.params.get("timeout", DEFAULT_REQUEST_TIMEOUT),
            max_retries=config.params.get("max_retries", DEFAULT_MAX_RETRIES),
        )

    @property
    def provider_name(self) -> str:
        """Human-readable provider name."""
        return "OpenAI"

    async def generate(self, prompt: str) -> str:
        """Generate text based on prompt using GPT.

        Args:
            prompt: The prompt to send to GPT

        Returns:
            Generated text response

        Raises:
            ProviderError: If generation fails
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            # Extract text from response
            content = response.choices[0].message.content
            return content if content else ""
        except Exception as e:
            raise ProviderError(
                f"Failed to generate text: {e}",
                self.provider_name,
                cause=e,
            ) from e

    async def generate_with_usage(self, prompt: str) -> tuple[str, Usage]:
        """Generate text and return OpenAI token usage by value (§6-F3).

        Reads prompt_tokens, completion_tokens, and
        usage.prompt_tokens_details.cached_tokens from the SDK response.
        Uses getattr(..., 0) or 0 everywhere so absent fields → 0 (truthful).
        """
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            u = getattr(response, "usage", None)
            pt_details = getattr(u, "prompt_tokens_details", None) if u else None
            usage = (
                Usage(
                    tokens_in=int(getattr(u, "prompt_tokens", 0) or 0),
                    tokens_out=int(getattr(u, "completion_tokens", 0) or 0),
                    cache_read=int(getattr(pt_details, "cached_tokens", 0) or 0),
                    cache_write=0,
                )
                if u is not None
                else Usage()
            )
            content = response.choices[0].message.content
            return (content if content else ""), usage
        except Exception as e:
            raise ProviderError(
                f"Failed to generate text: {e}",
                self.provider_name,
                cause=e,
            ) from e
