"""References API (Round 2 Plan C): list, semantic search, and backfill for
the lazy-tier reference catalog. Search embeds the query with the server's
embedding generator and brute-force cosine-ranks reference summaries.

Sensitivity is default-deny: the search endpoint hides rows marked
``sensitivity != 'normal'`` unless the request explicitly opts in via
``include_sensitive`` — the same request-flag mechanism the query path uses,
so MCP/dashboard/hooks (which never set it) can never surface sensitive rows."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from brainpalace_server.indexing import get_embedding_generator

logger = logging.getLogger(__name__)

router = APIRouter()


class ReferenceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    top_k: int = 5
    domain: str | None = None
    include_sensitive: bool = Field(
        default=False,
        description=(
            "Reveal references marked sensitivity != 'normal'. Default-deny: "
            "sensitive references are hidden unless this is true. Only the "
            "interactive CLI sets it; MCP/dashboard/hooks omit it."
        ),
    )


def _get_store(request: Request) -> Any:
    store = getattr(request.app.state, "reference_catalog_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Reference catalog is not available on this server.",
        )
    return store


async def _embed_query(text: str) -> list[float]:
    """Embed a query string, mapping any embedder failure to 503 (mirrors the
    ingest router's provider-error → 503 contract)."""
    from brainpalace_server.providers.exceptions import ProviderError

    try:
        gen = get_embedding_generator()
        return await gen.embed_query(text)
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Reference search is not available (no embedding provider "
                f"configured?): {exc}"
            ),
        ) from exc


@router.get(
    "",
    summary="List references (optionally filtered by domain)",
)
async def list_references(
    request: Request, domain: str | None = None
) -> dict[str, Any]:
    """GET /references?domain= → {references: [ReferenceEntry, ...]}."""
    store = _get_store(request)
    return {"references": [e.model_dump() for e in store.list(domain=domain)]}


@router.post(
    "/search",
    summary="Semantic search over reference summaries",
    description=(
        "Embeds the query and brute-force cosine-ranks reference summaries. "
        "Non-normal sensitivity references are hidden unless include_sensitive "
        "is set. 503 when no embedding provider is configured."
    ),
)
async def search_references(
    body: ReferenceSearchRequest, request: Request
) -> dict[str, Any]:
    """POST /references/search {query, top_k?, domain?, include_sensitive?}."""
    store = _get_store(request)
    query_embedding = await _embed_query(body.query)
    hits = store.search_summaries(
        query_embedding,
        top_k=body.top_k,
        domain=body.domain,
        include_sensitive=body.include_sensitive,
    )
    return {
        "results": [{**entry.model_dump(), "score": score} for entry, score in hits]
    }


@router.post(
    "/embed-missing",
    summary="Backfill embeddings for references that lack one",
    description=(
        "Embeds the summaries of every reference with no stored embedding and "
        "attaches them, making previously-unembedded references searchable. "
        "503 when no embedding provider is configured."
    ),
)
async def embed_missing(request: Request) -> dict[str, int]:
    """POST /references/embed-missing → {embedded: int}."""
    from brainpalace_server.providers.exceptions import ProviderError

    store = _get_store(request)
    pending = store.unembedded_entries()
    if not pending:
        return {"embedded": 0}
    try:
        gen = get_embedding_generator()
        vectors = await gen.embed_texts([e.summary for e in pending])
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Reference backfill is not available (no embedding provider "
                f"configured?): {exc}"
            ),
        ) from exc
    embedded = store.set_embeddings(list(zip((e.id for e in pending), vectors)))
    return {"embedded": embedded}
