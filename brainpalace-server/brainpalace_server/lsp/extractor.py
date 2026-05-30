"""Index-time LSP cross-reference extraction (Phase 150).

Bridges code-chunk metadata (file_path + symbol + line, already produced by the
AST layer) to :func:`extract_cross_refs`. Manages one lazily-spawned, lazily-
initialised language server per language id, cached for the indexing run.

Entirely opt-in (``BRAINPALACE_LSP_LANGUAGES``) and fail-soft: a disabled
language, a missing server binary, or a server crash yields no triplets and
never raises into the indexing pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from brainpalace_server.lsp import servers
from brainpalace_server.lsp.client import LspClient
from brainpalace_server.lsp.cross_refs import extract_cross_refs
from brainpalace_server.models.graph import GraphTriple

logger = logging.getLogger(__name__)


def _default_factory(language: str) -> Any | None:
    cmd = servers.server_command(language)
    if not cmd:
        return None
    try:
        client = LspClient.spawn(cmd)
        return client
    except (FileNotFoundError, OSError) as exc:  # server binary absent
        logger.debug("lsp spawn failed for %s: %s", language, exc)
        return None


class LspCrossRefExtractor:
    """Produce LSP cross-reference triplets from code-chunk metadata."""

    def __init__(
        self,
        root_uri: str = "",
        client_factory: Callable[[str], Any | None] | None = None,
    ) -> None:
        self.root_uri = root_uri
        self._factory = client_factory or _default_factory
        self._clients: dict[str, Any | None] = {}  # language -> client | None

    def _client_for(self, language: str) -> Any | None:
        if language not in self._clients:
            client = self._factory(language)
            if client is not None:
                try:
                    client.initialize(self.root_uri)
                except Exception as exc:  # noqa: BLE001 — fail-soft
                    logger.debug("lsp initialize failed for %s: %s", language, exc)
                    client = None
            self._clients[language] = client
        return self._clients[language]

    def extract_from_metadata(
        self, metadata: dict[str, Any], source_chunk_id: str | None = None
    ) -> list[GraphTriple]:
        file_path = metadata.get("file_path") or metadata.get("source")
        symbol_name = metadata.get("symbol_name")
        start_line = metadata.get("start_line")
        if not file_path or not symbol_name or start_line is None:
            return []

        language = metadata.get("language") or servers.language_for_path(file_path)
        if not language or not servers.is_language_enabled(language):
            return []

        client = self._client_for(language)
        if client is None:
            return []

        try:
            return extract_cross_refs(
                client,
                file_path=file_path,
                symbol_name=symbol_name,
                line=max(0, int(start_line) - 1),  # metadata is 1-based
                character=0,
                source_chunk_id=source_chunk_id,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.debug("lsp extract failed for %s: %s", file_path, exc)
            return []

    def close(self) -> None:
        for client in self._clients.values():
            if client is not None:
                try:
                    client.shutdown()
                except Exception:  # noqa: BLE001
                    pass
        self._clients.clear()
