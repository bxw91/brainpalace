"""Static embedding price table for the dashboard cost estimate.

USD per **million** tokens, as published by providers (snapshot 2026-06 —
update when providers change pricing). ``None`` from the lookup means
"unknown or local/free"; the economics endpoint then reports no dollar
estimate rather than a wrong one.
"""

from __future__ import annotations

EMBEDDING_PRICES_USD_PER_MTOK: dict[tuple[str, str], float] = {
    ("openai", "text-embedding-3-small"): 0.02,
    ("openai", "text-embedding-3-large"): 0.13,
    ("openai", "text-embedding-ada-002"): 0.10,
    ("voyage", "voyage-3.5"): 0.06,
    ("voyage", "voyage-3.5-lite"): 0.02,
    ("voyage", "voyage-code-3"): 0.18,
    ("cohere", "embed-v4.0"): 0.12,
}


def lookup_embedding_price(provider: str, model: str) -> float | None:
    """USD per 1M tokens for (provider, model); None when unknown/local."""
    return EMBEDDING_PRICES_USD_PER_MTOK.get((provider.lower(), model.lower()))
