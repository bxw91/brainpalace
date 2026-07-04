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
from pathlib import Path
from typing import Any

from brainpalace_server.lsp import servers
from brainpalace_server.lsp.client import LspClient
from brainpalace_server.lsp.cross_refs import extract_cross_refs, extract_reference
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
        self._opened: set[tuple[int, str]] = set()  # (id(client), file_path)
        self._fqname_lines: dict[str, dict[int, str]] = {}  # path -> line -> fq

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

    def _ensure_open(self, client: Any, language: str, file_path: str) -> None:
        """Send textDocument/didOpen once per (client, file) — real servers
        only answer position queries on opened documents. Text is read from
        disk (indexing passes absolute paths). Fail-soft on any error."""
        key = (id(client), file_path)
        if key in self._opened:
            return
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("lsp didOpen skipped for %s: %s", file_path, exc)
            return
        try:
            client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": f"file://{file_path}",
                        "languageId": language,
                        "version": 1,
                        "text": text,
                    }
                },
            )
            self._opened.add(key)
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.debug("lsp didOpen failed for %s: %s", file_path, exc)

    def _fqname_at(self, path: str, line: int, fallback: str) -> str:
        """fqname of the symbol defined at `line` (0-based) of `path`.

        Uses the target file's own AST symbol table (cached), so LSP targets
        merge with the AST layer's `file:fqname` ids — a cross-file method
        call lands on `file.py:C.m`, not a duplicate `file.py:m` node.
        Non-Python paths and unknown lines fall back to the reported name."""
        if not path.endswith((".py", ".pyi")):
            return fallback
        lines = self._fqname_lines.get(path)
        if lines is None:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._fqname_lines[path] = {}
                return fallback
            from brainpalace_server.indexing.code_symbol_extractor import (  # noqa: PLC0415 — avoid indexing<->lsp import cycle
                extract_python_symbols,
            )

            fs = extract_python_symbols(path, text)
            lines = {s.line: s.fqname for s in fs.symbols}
            self._fqname_lines[path] = lines
        return lines.get(line, fallback)

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

        self._ensure_open(client, language, file_path)
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

    def extract_from_symbols(
        self, symbols: list[Any], source_chunk_id: str | None = None
    ) -> list[GraphTriple]:
        """Query the language server for each symbol in the AST table.

        Keyed on the symbol's canonical `file:fqname`, so LSP triplets merge
        cleanly with the AST layer (§4). Gated per-language + fail-soft.
        """
        out: list[GraphTriple] = []
        for sym in symbols:
            language = getattr(sym, "language", None) or servers.language_for_path(
                sym.file_path
            )
            if not language or not servers.is_language_enabled(language):
                continue
            client = self._client_for(language)
            if client is None:
                continue
            self._ensure_open(client, language, sym.file_path)
            try:
                out.extend(
                    extract_cross_refs(
                        client,
                        file_path=sym.file_path,
                        symbol_name=sym.fqname,
                        line=sym.line,
                        character=sym.character,
                        source_chunk_id=source_chunk_id,
                        target_fqname=self._fqname_at,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — fail-soft
                logger.debug(
                    "lsp extract_from_symbols failed for %s: %s", sym.fqname, exc
                )
        return out

    def extract_references(
        self, sites: list[Any], source_chunk_id: str | None = None
    ) -> list[GraphTriple]:
        """``references`` triples for annotation sites (§5b — LSP-only, exact)."""
        out: list[GraphTriple] = []
        for site in sites:
            language = getattr(site, "language", None) or servers.language_for_path(
                site.file_path
            )
            if not language or not servers.is_language_enabled(language):
                continue
            client = self._client_for(language)
            if client is None:
                continue
            self._ensure_open(client, language, site.file_path)
            try:
                triple = extract_reference(
                    client,
                    file_path=site.file_path,
                    caller_id=site.caller_id,
                    name=site.name,
                    line=site.line,
                    character=site.character,
                    source_chunk_id=source_chunk_id,
                )
                if triple is not None:
                    out.append(triple)
            except Exception as exc:  # noqa: BLE001 — fail-soft
                logger.debug("lsp extract_references failed for %s: %s", site.name, exc)
        return out

    def close(self) -> None:
        for client in self._clients.values():
            if client is not None:
                try:
                    client.shutdown()
                except Exception:  # noqa: BLE001
                    pass
        self._clients.clear()
        self._opened.clear()
        self._fqname_lines.clear()
