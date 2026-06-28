"""Async provider-based doc-triplet extractor (Unified Extraction, Plan 2).

Reuses the shared prompt/parser primitives but routes the LLM call through the
shared summarization provider (``await provider.generate(prompt)``) instead of a
hardcoded Anthropic client. Pure async; never raises — returns [] on empty input
or provider failure so the reconciler leaves the chunk pending for a later retry.
"""

from __future__ import annotations

import logging
from typing import Protocol

from brainpalace_server.indexing.graph_extractors import (
    build_extraction_prompt,
    parse_triplets,
)
from brainpalace_server.models.graph import GraphTriple

logger = logging.getLogger(__name__)


class _Provider(Protocol):
    async def generate(self, prompt: str) -> str: ...


async def extract_doc_triplets(
    text: str,
    source_chunk_id: str | None,
    *,
    provider: _Provider,
    max_triplets: int = 10,
    max_chars: int = 4000,
) -> list[GraphTriple] | None:
    """Extract graph triplets from doc prose via the summarization provider.

    ``[]`` = empty input OR a successful call with no relations (mark done).
    ``None`` = provider error (leave the chunk pending for a later retry).
    """
    if not text or not text.strip():
        return []
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    prompt = build_extraction_prompt(text, max_triplets)
    try:
        response = await provider.generate(prompt)
    except Exception as exc:  # noqa: BLE001 — provider error ⇒ leave pending
        logger.warning("doc triplet extraction failed (%s): %s", source_chunk_id, exc)
        return None
    return parse_triplets(response, source_chunk_id)
