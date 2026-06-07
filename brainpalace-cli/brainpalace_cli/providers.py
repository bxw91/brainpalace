"""Canonical provider descriptor — the single source of truth for which models,
endpoints, and API-key env vars each provider supports, per kind.

Import-light by design (no heavy deps): consumed by the CLI ``config wizard``
(model suggestions) and by the dashboard ``ui_schema`` (model presets, base_url
visibility, api_key_env placeholders) and exposed to the dashboard frontend via
``GET /schema``. The README provider tables mirror these lists.

Model IDs are sourced from the repo's CURRENT authoritative lists (README
provider tables + server provider modules + the CLI wizard defaults). The
``default_api_key_env`` values mirror the server's provider-config conventions
(``brainpalace_server.config.provider_config``): openai->OPENAI_API_KEY,
cohere->COHERE_API_KEY, anthropic->ANTHROPIC_API_KEY, gemini->GEMINI_API_KEY,
grok->XAI_API_KEY, and ``None`` for local Ollama.

The first model in each ``models`` list is the recommended default.
``needs_base_url`` is True for providers that talk to a custom/local endpoint
(Ollama, and Grok's OpenAI-compatible x.ai endpoint).
"""

from __future__ import annotations

from typing import Any, TypedDict


class ProviderInfo(TypedDict):
    models: list[str]  # first entry = recommended default
    needs_base_url: bool
    default_api_key_env: str | None


# kind -> provider -> ProviderInfo
PROVIDERS: dict[str, dict[str, ProviderInfo]] = {
    "embedding": {
        "openai": {
            "models": ["text-embedding-3-large", "text-embedding-3-small"],
            "needs_base_url": False,
            "default_api_key_env": "OPENAI_API_KEY",
        },
        "cohere": {
            "models": ["embed-english-v3.0", "embed-multilingual-v3.0"],
            "needs_base_url": False,
            "default_api_key_env": "COHERE_API_KEY",
        },
        "ollama": {
            "models": ["nomic-embed-text", "mxbai-embed-large"],
            "needs_base_url": True,
            "default_api_key_env": None,
        },
    },
    "summarization": {
        "anthropic": {
            "models": [
                "claude-haiku-4-5-20251001",
                "claude-sonnet-4-5-20250514",
            ],
            "needs_base_url": False,
            "default_api_key_env": "ANTHROPIC_API_KEY",
        },
        "openai": {
            "models": ["gpt-5-mini", "gpt-5"],
            "needs_base_url": False,
            "default_api_key_env": "OPENAI_API_KEY",
        },
        "gemini": {
            "models": ["gemini-3.1-flash-lite", "gemini-3.5-flash"],
            "needs_base_url": False,
            "default_api_key_env": "GEMINI_API_KEY",
        },
        "grok": {
            "models": ["grok-4", "grok-4-fast"],
            "needs_base_url": True,
            "default_api_key_env": "XAI_API_KEY",
        },
        "ollama": {
            "models": ["llama4:scout", "mistral-small3.2", "qwen3-coder"],
            "needs_base_url": True,
            "default_api_key_env": None,
        },
    },
    "reranker": {
        "sentence-transformers": {
            "models": [
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "cross-encoder/ms-marco-MiniLM-L-12-v2",
            ],
            "needs_base_url": False,
            "default_api_key_env": None,
        },
        "ollama": {
            "models": ["llama3.2:1b"],
            "needs_base_url": True,
            "default_api_key_env": None,
        },
    },
}


def recommended_model(kind: str, provider: str) -> str | None:
    """First (recommended) model for a kind/provider, or None if unknown."""
    info = PROVIDERS.get(kind, {}).get(provider)
    return info["models"][0] if info and info["models"] else None


def descriptor() -> dict[str, dict[str, Any]]:
    """Plain-dict copy of PROVIDERS for JSON payloads (e.g. GET /schema)."""
    return {
        kind: {prov: dict(info) for prov, info in provs.items()}
        for kind, provs in PROVIDERS.items()
    }
