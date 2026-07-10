"""BM25 index manager — bm25s engine + per-language tokenization (BrainPalace-owned)."""

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bm25s
from llama_index.core.schema import BaseNode, NodeWithScore, TextNode
from llama_index.core.vector_stores.utils import metadata_dict_to_node

from brainpalace_server.config import settings
from brainpalace_server.config.bm25_config import load_bm25_config
from brainpalace_server.indexing.text_analysis import get_analyzer

if TYPE_CHECKING:
    from brainpalace_server.indexing.text_analysis import TextAnalyzer

logger = logging.getLogger(__name__)
_CONFIG_FILE = "analyzer_config.json"
_SCHEMA_VERSION = 1


class BM25IndexManager:
    """
    Manages the lifecycle of the BM25 index.

    Handles building the index from nodes, persisting it to disk,
    and loading it for retrieval. Uses the bm25s engine directly
    with per-language tokenization via the text_analysis package.
    """

    def __init__(
        self,
        persist_dir: str | None = None,
        default_lang: str | None = None,
        engine: str | None = None,
    ):
        """
        Initialize the BM25 index manager.

        Args:
            persist_dir: Directory for index persistence.
            default_lang: Default language for tokenization (e.g. "en", "hr").
            engine: Tokenization engine ("stem" or "lemma").
        """
        self.persist_dir = persist_dir or settings.BM25_INDEX_PATH
        if default_lang is None or engine is None:
            cfg = load_bm25_config()
            default_lang = default_lang or cfg.language
            engine = engine or cfg.engine
        self.default_lang = default_lang
        self.engine = engine
        self._bm25: bm25s.BM25 | None = None
        self._corpus: list[dict[str, Any]] | None = None

    @property
    def is_initialized(self) -> bool:
        """Check if the index is initialized."""
        return self._bm25 is not None

    @property
    def corpus_size(self) -> int:
        """Get the number of documents in the BM25 index."""
        return len(self._corpus) if self._corpus else 0

    def all_nodes(self) -> list[BaseNode]:
        """All indexed chunks as nodes (text + metadata).

        Reconstructs ``TextNode``s from the persisted corpus so callers (e.g.
        graph rebuild) can re-run extraction over every chunk without
        re-embedding. Skips entries with an unreadable payload.
        """
        nodes: list[BaseNode] = []
        for entry in self._corpus or []:
            try:
                node_id, text, metadata = self._entry_to_fields(entry)
            except (ValueError, KeyError, TypeError):
                continue
            nodes.append(TextNode(text=text, metadata=metadata, id_=node_id or None))
        return nodes

    def _analyzer_for(self, lang: str) -> "TextAnalyzer":
        return get_analyzer("code" if lang == "code" else lang, self.engine)

    def _analyzer_versions(self) -> dict[str, str]:
        return {"hr": "ljubesic-pandzic@1", "snowball": "pystemmer@2", "code": "v1"}

    @staticmethod
    def _entry_to_fields(entry: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        """Return ``(node_id, text, metadata)`` for a corpus entry, handling
        BOTH the new BrainPalace shape and the legacy LlamaIndex shape.

        - New shape (written by :meth:`build_index`): top-level ``"node_id"``,
          ``"text"`` and ``"metadata"`` keys.
        - Legacy LlamaIndex ``BM25Retriever`` shape: the payload was written as
          ``node_to_metadata_dict(node) | {"node_id": node.node_id}`` — i.e. the
          node serialized into a flat metadata dict (``_node_content``,
          ``_node_type``, ``doc_id``/``document_id``, ``node_id``) with NO
          top-level ``"text"`` or ``"metadata"``. Reconstructed via the official
          ``metadata_dict_to_node`` inverse.

        Raises on a payload that matches neither shape (unreadable corpus) so the
        caller can degrade gracefully instead of silently dropping documents.
        """
        if "text" in entry and "metadata" in entry:
            return (
                entry.get("node_id", ""),
                entry["text"],
                dict(entry["metadata"]),
            )
        # Legacy LlamaIndex payload → reconstruct the node. Raises ValueError if
        # ``_node_content`` is absent (genuinely unreadable corpus).
        node = metadata_dict_to_node(entry)
        return node.node_id, node.get_content(), dict(node.metadata)

    @staticmethod
    def _guard_empty(tokens: list[str]) -> list[str]:
        """Return tokens, or ["__empty__"] if the list is empty.

        bm25s raises ``ValueError: max() iterable argument is empty`` when
        every document in an index() call produces an empty token list (empty
        vocabulary).  The placeholder keeps the document represented without
        ever matching a real query token.
        """
        return tokens if tokens else ["__empty__"]

    def build_index(self, nodes: Sequence[BaseNode]) -> None:
        """
        Build a new BM25 index from nodes and persist it.

        Args:
            nodes: List of LlamaIndex nodes.
        """
        if not nodes:
            logger.info("BM25 build_index: empty nodes; skipping (issue #143)")
            return
        corpus_tokens, corpus = [], []
        for node in nodes:
            lang = node.metadata.get("text_language", self.default_lang)
            tokens = self._analyzer_for(lang).analyze(node.get_content())
            # bm25s crashes on index([[]]) when vocab is empty; use placeholder
            # so the doc is represented but will never match a real query token.
            corpus_tokens.append(self._guard_empty(tokens))
            corpus.append(
                {
                    "node_id": node.node_id,
                    "text": node.get_content(),
                    "metadata": dict(node.metadata),
                }
            )
        self._bm25 = bm25s.BM25(corpus=corpus)
        self._bm25.index(corpus_tokens)
        self._corpus = corpus
        self.persist()

    def persist(self) -> None:
        """Persist the current index to disk."""
        if self._bm25 is None:
            logger.warning("No BM25 index to persist")
            return
        p = Path(self.persist_dir)
        p.mkdir(parents=True, exist_ok=True)
        self._bm25.save(str(p), corpus=self._corpus)
        (p / _CONFIG_FILE).write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "default_lang": self.default_lang,
                    "engine": self.engine,
                    "analyzer_versions": self._analyzer_versions(),
                }
            )
        )
        logger.info(f"BM25 index persisted to {self.persist_dir}")

    def initialize(self) -> None:
        """
        Load the index from disk if it exists.

        Idempotent: once the index is loaded, repeat calls are a no-op.
        The server lifespan calls this once explicitly and ChromaBackend
        calls it again during its own initialize() — the guard avoids the
        redundant second disk reload.
        """
        if self._bm25 is not None:
            return
        p = Path(self.persist_dir)
        index_exists = (p / "params.index.json").exists() or (
            p / "data.csc.index.npy"
        ).exists()
        if not index_exists:
            # A legacy LlamaIndex BM25Retriever always writes the bm25s params
            # files (params.index.json / data.csc.index.npy) next to its
            # retriever.json, so a real upgrade hits the index_exists branch
            # below — which now handles the legacy corpus shape via
            # rebuild_from_corpus(). If only retriever.json exists the bm25s
            # index is unusable and must be rebuilt from source.
            logger.info("No existing BM25 index found")
            return
        cfg_path = p / _CONFIG_FILE
        if not cfg_path.exists():
            try:
                self._bm25 = bm25s.BM25.load(str(p), load_corpus=True)
                self._corpus = list(self._bm25.corpus)
            except Exception as e:
                logger.error(
                    "BM25 index could not be loaded (%s). "
                    "Re-run `brainpalace index <path>` to rebuild.",
                    e,
                )
                self._bm25 = None
                return
            logger.warning("BM25 index has no analyzer_config; rebuilding from corpus")
            self.rebuild_from_corpus()
            return
        saved = json.loads(cfg_path.read_text())
        try:
            self._bm25 = bm25s.BM25.load(str(p), load_corpus=True)
            self._corpus = list(self._bm25.corpus)
        except Exception as e:
            logger.error(
                "BM25 index could not be loaded (%s). "
                "Re-run `brainpalace index <path>` to rebuild.",
                e,
            )
            self._bm25 = None
            return
        if (
            saved.get("engine") != self.engine
            or saved.get("analyzer_versions") != self._analyzer_versions()
            or saved.get("schema_version", 0) != _SCHEMA_VERSION
        ):
            logger.warning("BM25 analyzer fingerprint changed; rebuilding from corpus")
            # Intentional: keep self.engine/default_lang as-constructed so the
            # rebuild adopts the new config rather than loading the stale one.
            self.rebuild_from_corpus()
        else:
            self.default_lang = saved.get("default_lang", self.default_lang)
        logger.info(f"BM25 index loaded from {self.persist_dir}")

    def rebuild_from_corpus(self) -> None:
        """Re-tokenize the stored corpus with current analyzers. No re-embed.

        Robust to BOTH the new BrainPalace corpus shape and the legacy
        LlamaIndex ``BM25Retriever`` shape (see :meth:`_entry_to_fields`).
        After a successful rebuild ``self._corpus`` is normalized to the new
        shape and re-persisted (with ``analyzer_config.json``), so the next
        start takes the fast load path and never re-migrates.

        A genuinely unreadable legacy corpus (a payload matching neither shape)
        degrades gracefully: logs an actionable message and leaves
        ``self._bm25 = None`` rather than crashing startup — mirroring the
        ``bm25s.load`` guard philosophy in :meth:`initialize`.
        """
        if not self._corpus:
            return
        try:
            normalized: list[dict[str, Any]] = []
            toks: list[list[str]] = []
            for entry in self._corpus:
                node_id, text, metadata = self._entry_to_fields(entry)
                normalized.append(
                    {"node_id": node_id, "text": text, "metadata": metadata}
                )
                lang = metadata.get("text_language", self.default_lang)
                toks.append(self._guard_empty(self._analyzer_for(lang).analyze(text)))
        except Exception as e:
            logger.error(
                "BM25 corpus could not be read for rebuild (%s). "
                "Re-run `brainpalace index <path>` to rebuild.",
                e,
            )
            self._bm25 = None
            return
        self._corpus = normalized
        self._bm25 = bm25s.BM25(corpus=normalized)
        self._bm25.index(toks)
        self.persist()

    def add_chunks(self, entries: list[dict[str, Any]]) -> None:
        """Add/replace corpus entries by node_id, then re-tokenize + persist.

        Text-ingest path (spec Item 3): bm25s has no incremental index, so
        this is corpus mutation + rebuild_from_corpus (re-tokenize only —
        never re-embeds). Batched per ingest request by the caller."""
        if not entries:
            return
        incoming = {e["node_id"] for e in entries}
        corpus = self._corpus or []
        self._corpus = [
            e for e in corpus if self._entry_to_fields(e)[0] not in incoming
        ]
        self._corpus.extend(
            {
                "node_id": e["node_id"],
                "text": e["text"],
                "metadata": dict(e.get("metadata") or {}),
            }
            for e in entries
        )
        self.rebuild_from_corpus()

    def remove_chunks(self, node_ids: list[str]) -> None:
        """Remove corpus entries by node_id, then re-tokenize + persist."""
        if not self._corpus:
            return
        drop = set(node_ids)
        before = len(self._corpus)
        self._corpus = [
            e for e in self._corpus if self._entry_to_fields(e)[0] not in drop
        ]
        if len(self._corpus) == before:
            return
        if self._corpus:
            self.rebuild_from_corpus()
        else:
            # rebuild_from_corpus early-returns on an empty corpus (no
            # re-index to do) and persist() is a no-op once self._bm25 is
            # None, so neither makes the removal stick on disk. reset()
            # clears both in-memory state and the persisted index files,
            # which is exactly what an emptied corpus needs.
            self.reset()

    async def search_with_filters(
        self,
        query: str,
        top_k: int = 5,
        source_types: list[str] | None = None,
        languages: list[str] | None = None,
        max_results: int | None = None,
        language: str | None = None,
    ) -> list[NodeWithScore]:
        """
        Search the BM25 index with metadata filtering.

        Args:
            query: Search query string.
            top_k: Number of results to return.
            source_types: Filter by source types (doc, code, test).
            languages: Filter by programming languages.
            max_results: Override for internal retrieval count before filtering.
            language: Language hint for query tokenization (overrides default_lang).

        Returns:
            List of NodeWithScore objects, filtered by metadata.
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 index not initialized")
        analyzer = get_analyzer(language or self.default_lang, self.engine)
        q_tokens = analyzer.analyze(query)
        if not q_tokens or self.corpus_size == 0:
            return []
        k = max_results if max_results is not None else top_k * 3
        k = min(k, self.corpus_size)
        results, scores = self._bm25.retrieve([q_tokens], k=k)
        raw = [float(s) for s in scores[0]]
        hi = max(raw) if raw else 0.0
        nodes: list[NodeWithScore] = []
        for payload, s in zip(results[0], raw):
            norm = (s / hi) if hi > 0 else 0.0
            nodes.append(
                NodeWithScore(
                    node=TextNode(
                        id_=payload["node_id"],
                        text=payload["text"],
                        metadata=payload["metadata"],
                    ),
                    score=norm,
                )
            )
        out = []
        for n in nodes:
            md = n.node.metadata
            if source_types and md.get("source_type", "doc") not in source_types:
                continue
            if languages:
                lg = md.get("language")
                if not lg or lg not in languages:
                    continue
            out.append(n)
        return out[:top_k]

    def reset(self) -> None:
        """Reset the BM25 index by deleting persistent files."""
        self._bm25 = None
        self._corpus = None
        p = Path(self.persist_dir)
        if p.exists():
            for f in p.glob("*"):
                f.unlink()
            p.rmdir()
        logger.info("BM25 index reset")


# Global singleton instance
_bm25_manager: BM25IndexManager | None = None


def get_bm25_manager() -> BM25IndexManager:
    """Get the global BM25 manager instance."""
    global _bm25_manager
    if _bm25_manager is None:
        _bm25_manager = BM25IndexManager()
    return _bm25_manager


def set_bm25_manager(instance: BM25IndexManager) -> None:
    """Replace the global BM25IndexManager singleton.

    Used by the server lifespan to register a manager constructed with the
    correct project-resolved persist_dir, so later get_bm25_manager() calls
    (e.g. from ChromaBackend) reuse it instead of building a CWD-relative one.
    """
    global _bm25_manager
    _bm25_manager = instance
