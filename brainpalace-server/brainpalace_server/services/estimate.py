"""Server-less, in-process embedding-token estimate.

Lets ``brainpalace init`` show the estimate BEFORE starting a server or writing
any index data. Builds only a ``DocumentLoader`` (no storage, no embedder, no
graph manager) and reuses ``IndexingService.estimate_tokens`` so the estimate
has exactly one source of truth.
"""

from __future__ import annotations

import os
from typing import Any


class _NoopCollaborator:
    """Stand-in for the storage / embedding / graph collaborators.

    ``IndexingService.estimate_tokens`` never touches any of them, but
    ``IndexingService.__init__`` otherwise builds them via factory functions
    (which open ChromaDB / construct embedding providers). Passing an object
    that exposes the attributes ``__init__`` reads short-circuits every factory
    call, keeping the estimate path free of storage and provider initialization.
    """

    vector_store = None
    bm25_manager = None


async def estimate_tokens_local(
    folder_path: str,
    *,
    include_code: bool = True,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Estimate embedding-token cost for ``folder_path`` with no server/storage.

    Args:
        folder_path: Project root to estimate.
        include_code: Whether to count code files (mirrors the index request).
        config_path: Optional ``config.yaml`` to resolve providers/git/sessions
            from; exported as ``BRAINPALACE_CONFIG`` for the duration of the call.

    Returns:
        The same dict shape as ``IndexingService.estimate_tokens``.
    """
    from brainpalace_server.config.provider_config import clear_settings_cache
    from brainpalace_server.indexing.document_loader import DocumentLoader
    from brainpalace_server.models.index import IndexRequest
    from brainpalace_server.services.indexing_service import IndexingService

    # Point config resolution at the requested file for the duration of the call,
    # then restore the prior environment + settings cache so a one-shot estimate
    # never leaks the temporary config into the rest of the process (important
    # for in-process callers like `brainpalace init`).
    _prev = os.environ.get("BRAINPALACE_CONFIG")
    if config_path:
        os.environ["BRAINPALACE_CONFIG"] = config_path
    clear_settings_cache()
    try:
        # estimate_tokens only reads self.document_loader + config; the noop
        # collaborators keep storage/embedding/graph factories from running.
        # The noop stand-ins are deliberately the wrong type — estimate_tokens
        # never calls them; they only exist to short-circuit __init__'s factory
        # calls. Suppress the arg-type mismatch rather than widen the real API.
        service = IndexingService(
            document_loader=DocumentLoader(),
            storage_backend=_NoopCollaborator(),  # type: ignore[arg-type]
            embedding_generator=_NoopCollaborator(),  # type: ignore[arg-type]
            graph_index_manager=_NoopCollaborator(),  # type: ignore[arg-type]
        )
        return await service.estimate_tokens(
            IndexRequest(folder_path=folder_path, include_code=include_code)
        )
    finally:
        if config_path:
            if _prev is None:
                os.environ.pop("BRAINPALACE_CONFIG", None)
            else:
                os.environ["BRAINPALACE_CONFIG"] = _prev
            clear_settings_cache()
