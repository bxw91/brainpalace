"""Chroma vector store manager with thread-safe operations."""

import asyncio
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from brainpalace_server.config import settings
from brainpalace_server.providers.exceptions import ProviderMismatchError
from brainpalace_server.storage_paths import STATE_SUBDIR

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result from a similarity search."""

    text: str
    metadata: dict[str, Any]
    score: float
    chunk_id: str


@dataclass
class EmbeddingMetadata:
    """Metadata about the embedding provider used for this collection."""

    provider: str
    model: str
    dimensions: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for ChromaDB metadata."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingMetadata":
        """Create from dictionary (ChromaDB metadata)."""
        return cls(
            provider=data.get("embedding_provider", "unknown"),
            model=data.get("embedding_model", "unknown"),
            dimensions=data.get("embedding_dimensions", 0),
        )


class VectorStoreManager:
    """
    Manages Chroma vector store operations with thread-safe access.

    This class provides a high-level interface for storing and retrieving
    document embeddings using Chroma as the backend.
    """

    def __init__(
        self,
        persist_dir: str | None = None,
        collection_name: str | None = None,
    ):
        """
        Initialize the vector store manager.

        Args:
            persist_dir: Directory for persistent storage. Defaults to config value.
            collection_name: Name of the collection. Defaults to config value.
        """
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.collection_name = collection_name or settings.COLLECTION_NAME
        self._client: chromadb.PersistentClient | None = None  # type: ignore[valid-type]
        self._collection: chromadb.Collection | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the vector store is initialized."""
        return self._initialized and self._collection is not None

    async def initialize(self) -> None:
        """
        Initialize the Chroma client and collection.

        Creates the persistence directory if it doesn't exist and
        initializes or loads the existing collection.
        """
        async with self._lock:
            if self._initialized:
                return

            # Ensure persistence directory exists
            persist_path = Path(self.persist_dir)
            persist_path.mkdir(parents=True, exist_ok=True)

            # Initialize Chroma client
            self._client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )

            # Get or create collection
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            self._initialized = True
            logger.info(
                f"Vector store initialized: {self.collection_name} "
                f"({self._collection.count()} existing documents)"
            )

    async def get_embedding_metadata(self) -> EmbeddingMetadata | None:
        """Get stored embedding metadata from collection.

        Returns:
            EmbeddingMetadata if collection has metadata, None otherwise.
        """
        if not self.is_initialized or self._collection is None:
            return None

        async with self._lock:
            metadata = self._collection.metadata
            if metadata and "embedding_provider" in metadata:
                return EmbeddingMetadata.from_dict(metadata)
            return None

    async def set_embedding_metadata(
        self,
        provider: str,
        model: str,
        dimensions: int,
    ) -> None:
        """Store embedding metadata in collection.

        Args:
            provider: Embedding provider name (e.g., "openai", "ollama")
            model: Model name (e.g., "text-embedding-3-large")
            dimensions: Embedding vector dimensions
        """
        if not self.is_initialized or self._collection is None:
            raise RuntimeError("Vector store not initialized")

        async with self._lock:
            assert self._client is not None
            # ChromaDB requires recreating collection to update metadata
            # Get existing metadata and merge
            existing_meta = {
                key: value
                for key, value in (self._collection.metadata or {}).items()
                if key != "hnsw:space"
            }
            existing_meta.update(
                {
                    "embedding_provider": provider,
                    "embedding_model": model,
                    "embedding_dimensions": dimensions,
                }
            )

            # Modify collection metadata (avoid updating hnsw:space)
            self._collection.modify(metadata=existing_meta)

            logger.info(
                f"Stored embedding metadata: {provider}/{model} "
                f"({dimensions} dimensions)"
            )

    def validate_embedding_compatibility(
        self,
        provider: str,
        model: str,
        dimensions: int,
        stored_metadata: EmbeddingMetadata | None,
    ) -> None:
        """Validate current embedding config against stored metadata.

        Args:
            provider: Current provider name
            model: Current model name
            dimensions: Current embedding dimensions
            stored_metadata: Previously stored metadata (or None if new index)

        Raises:
            ProviderMismatchError: If dimensions or provider/model don't match
        """
        if stored_metadata is None:
            return  # New index, no validation needed

        # Check dimension mismatch first (critical)
        if stored_metadata.dimensions != dimensions:
            raise ProviderMismatchError(
                current_provider=provider,
                current_model=model,
                indexed_provider=stored_metadata.provider,
                indexed_model=stored_metadata.model,
            )

        # Check provider/model mismatch (even same dimensions can be incompatible)
        if stored_metadata.provider != provider or stored_metadata.model != model:
            raise ProviderMismatchError(
                current_provider=provider,
                current_model=model,
                indexed_provider=stored_metadata.provider,
                indexed_model=stored_metadata.model,
            )

    async def add_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """
        Add documents with embeddings to the vector store.

        Args:
            ids: Unique identifiers for each document.
            embeddings: Embedding vectors for each document.
            documents: Text content of each document.
            metadatas: Optional metadata for each document.

        Returns:
            Number of documents added.
        """
        if not self.is_initialized:
            raise RuntimeError("Vector store not initialized. Call initialize() first.")

        if not (len(ids) == len(embeddings) == len(documents)):
            raise ValueError("ids, embeddings, and documents must have the same length")

        async with self._lock:
            assert self._collection is not None
            self._collection.add(
                ids=ids,
                embeddings=embeddings,  # type: ignore[arg-type]
                documents=documents,
                metadatas=metadatas or [{}] * len(ids),  # type: ignore[arg-type]
            )

        logger.debug(f"Added {len(ids)} documents to vector store")
        return len(ids)

    async def upsert_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> int:
        """
        Upsert documents with embeddings to the vector store.
        If IDs already exist, the content and embeddings will be updated.

        Args:
            ids: Unique identifiers for each document.
            embeddings: Embedding vectors for each document.
            documents: Text content of each document.
            metadatas: Optional metadata for each document.

        Returns:
            Number of documents upserted.
        """
        if not self.is_initialized:
            raise RuntimeError("Vector store not initialized. Call initialize() first.")

        if not (len(ids) == len(embeddings) == len(documents)):
            raise ValueError("ids, embeddings, and documents must have the same length")

        # Resolve metadatas before deduplication so the dict is keyed
        # with the correct (emb, doc, meta) tuples.
        safe_metadatas = metadatas or [{}] * len(ids)

        # Deduplicate by ID with last-occurrence-wins semantics.
        # This prevents ChromaDB's DuplicateIDError when two files in a
        # corpus share the same filename (e.g. Confluence exports).
        seen: dict[str, tuple[list[float], str, dict[str, Any]]] = {}
        for id_, emb, doc, meta in zip(
            ids, embeddings, documents, safe_metadatas, strict=True
        ):
            seen[id_] = (emb, doc, meta)

        if len(seen) < len(ids):
            dup_count = len(ids) - len(seen)
            # Build a sample of the IDs that were duplicated for debuggability
            sample_dups = list({i for i in ids if ids.count(i) > 1})[:5]
            logger.warning(
                f"upsert_documents: removed {dup_count} duplicate chunk ID(s) "
                f"from batch of {len(ids)}. Keeping last occurrence. "
                f"Sample duplicate IDs: {sample_dups}"
            )
            ids = list(seen.keys())
            embeddings = [v[0] for v in seen.values()]
            documents = [v[1] for v in seen.values()]
            safe_metadatas = [v[2] for v in seen.values()]

        async with self._lock:
            assert self._collection is not None
            collection = self._collection

            # ChromaDB upsert is synchronous and CPU/IO-heavy for large
            # batches.  Run in a thread so the event loop stays responsive
            # for concurrent HTTP requests (e.g. cache clear, health).
            def _upsert() -> None:
                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,  # type: ignore[arg-type]
                    documents=documents,
                    metadatas=safe_metadatas,  # type: ignore[arg-type]
                )

            await asyncio.to_thread(_upsert)

        logger.debug(f"Upserted {len(ids)} documents to vector store")
        return len(ids)

    async def similarity_search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        where: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Perform similarity search on the vector store.

        Args:
            query_embedding: Embedding vector to search for.
            top_k: Maximum number of results to return.
            similarity_threshold: Minimum similarity score (0-1).
            where: Optional metadata filter.

        Returns:
            List of SearchResult objects sorted by score descending.

        Raises:
            RuntimeError: If the store is not initialized.
        """
        if not self.is_initialized:
            raise RuntimeError("Vector store not initialized. Call initialize() first.")

        async with self._lock:
            assert self._collection is not None
            results = self._collection.query(
                query_embeddings=[query_embedding],  # type: ignore[arg-type]
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],  # type: ignore[list-item]
            )

        # Convert Chroma results to SearchResult objects
        search_results: list[SearchResult] = []

        if results["ids"] and results["ids"][0]:
            for idx, chunk_id in enumerate(results["ids"][0]):
                # Chroma returns distances, convert to similarity (cosine)
                distances = results["distances"]
                distance = distances[0][idx] if distances else 0.0
                similarity = 1 - distance  # Cosine distance to similarity

                if similarity >= similarity_threshold:
                    documents = results["documents"]
                    metadatas = results["metadatas"]
                    text_val = documents[0][idx] if documents else ""
                    meta_val: dict[str, Any] = {}
                    if metadatas and metadatas[0][idx]:
                        meta_val = dict(metadatas[0][idx])
                    search_results.append(
                        SearchResult(
                            text=text_val,
                            metadata=meta_val,
                            score=similarity,
                            chunk_id=chunk_id,
                        )
                    )

        # Sort by score descending
        search_results.sort(key=lambda x: x.score, reverse=True)

        logger.debug(
            f"Similarity search returned {len(search_results)} results "
            f"(threshold: {similarity_threshold})"
        )
        return search_results

    async def get_count(self, where: dict[str, Any] | None = None) -> int:
        """
        Get the number of documents in the collection, optionally filtered.

        Args:
            where: Optional metadata filter.

        Returns:
            Number of documents stored.
        """
        if not self.is_initialized:
            return 0

        async with self._lock:
            assert self._collection is not None
            if where:
                # get() is the only way to filter for counts in some Chroma versions
                # include=[] to minimize data transfer
                results = self._collection.get(where=where, include=[])
                if results and "ids" in results:
                    return len(results["ids"])
                return 0
            return self._collection.count()

    async def get_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        """
        Get a document by its chunk ID.

        Args:
            chunk_id: The unique identifier of the chunk.

        Returns:
            Dictionary with 'text', 'metadata' and 'embedding' keys, or None
            if not found. 'embedding' lets embed-frugal callers (e.g. the
            text-ingest metadata refresh) reuse the stored vector without
            re-embedding unchanged text.
        """
        if not self.is_initialized:
            return None

        async with self._lock:
            assert self._collection is not None
            try:
                results = self._collection.get(
                    ids=[chunk_id],
                    include=["documents", "metadatas", "embeddings"],  # type: ignore[list-item]
                )

                if results["ids"] and results["ids"]:
                    documents = results.get("documents", [[]])
                    metadatas = results.get("metadatas", [[]])
                    embeddings = results.get("embeddings", [[]])
                    text = documents[0] if documents else ""
                    metadata = metadatas[0] if metadatas else {}
                    embedding = (
                        embeddings[0]
                        if embeddings is not None and len(embeddings) > 0
                        else None
                    )
                    return {
                        "text": text,
                        "metadata": metadata if metadata else {},
                        "embedding": embedding,
                    }
            except Exception as e:
                logger.warning(f"Failed to get document by ID {chunk_id}: {e}")

            return None

    async def get_existing_ids(self, ids: list[str]) -> set[str]:
        """Return the subset of ``ids`` that currently exist in the collection.

        Batched ``collection.get(ids=...)`` reads SQLite only and returns just
        the ids that exist, so this is a cheap existence probe — used by the
        startup reconcile to detect chunks the store has *lost* relative to the
        manifest (e.g. after a corrupt/healed HNSW shed live vectors). Never
        raises: a backend error yields whatever was confirmed so far, so the
        caller treats unconfirmed ids as missing rather than crashing startup.
        """
        if not self.is_initialized or not ids:
            return set()
        found: set[str] = set()
        async with self._lock:
            assert self._collection is not None
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                try:
                    res = self._collection.get(ids=batch, include=[])  # ids only
                    found.update(res.get("ids") or [])
                except Exception as e:  # noqa: BLE001 — never fail the probe
                    logger.warning("get_existing_ids batch failed: %s", e)
        return found

    async def get_ids_by_where(self, where: dict[str, Any]) -> set[str]:
        """Return all chunk ids matching a metadata filter (read-only).

        SQLite-only id probe (``collection.get(where=..., include=[])``) used by
        the manifest-orphan cleanup to enumerate the store's live ``code``/``doc``
        chunks. Never raises: a backend error yields the empty set so the caller
        treats "can't enumerate" as "nothing to clean" rather than crashing.
        """
        if not self.is_initialized:
            return set()
        async with self._lock:
            assert self._collection is not None
            try:
                res = self._collection.get(where=where, include=[])
                return set(res.get("ids") or [])
            except Exception as e:  # noqa: BLE001 — never fail the probe
                logger.warning("get_ids_by_where failed: %s", e)
                return set()

    async def get_id_source_pairs(self, where: dict[str, Any]) -> list[tuple[str, str]]:
        """Return ``(chunk_id, source)`` for every chunk matching ``where``.

        Used by the existence-based purges (e.g. drop ``session_turn`` chunks
        whose source transcript is gone from disk). ``source`` is the empty
        string when a chunk has no recorded source. Never raises — yields an
        empty list on any backend error so the caller cleans nothing.
        """
        if not self.is_initialized:
            return []
        async with self._lock:
            assert self._collection is not None
            try:
                res = self._collection.get(
                    where=where,
                    include=["metadatas"],  # type: ignore[list-item]
                )
            except Exception as e:  # noqa: BLE001 — never fail the probe
                logger.warning("get_id_source_pairs failed: %s", e)
                return []
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        pairs: list[tuple[str, str]] = []
        for i, cid in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            pairs.append((cid, str((meta or {}).get("source", "") or "")))
        return pairs

    async def delete_by_where(self, where: dict[str, Any]) -> int:
        """Delete documents matching a metadata filter and return count.

        Queries the collection with the given ``where`` filter to discover
        matching IDs, then deletes those IDs.  This two-step approach is
        required because ChromaDB's ``collection.delete(where=...)`` does
        not return the number of documents deleted.

        CRITICAL GUARD: If the resulting ID list is empty, this method
        returns 0 immediately.  Passing ``ids=[]`` to
        ``collection.delete()`` in ChromaDB wipes the **entire** collection,
        which is almost never what the caller wants.

        Args:
            where: ChromaDB ``where`` metadata filter.

        Returns:
            Number of documents deleted (0 if no matching documents).

        Raises:
            RuntimeError: If the vector store is not initialized.
        """
        if not self.is_initialized:
            raise RuntimeError("Vector store not initialized. Call initialize() first.")

        async with self._lock:
            assert self._collection is not None

            # Step 1: Find matching IDs
            results = self._collection.get(where=where, include=[])
            matching_ids: list[str] = results.get("ids", []) or []

            # Step 2: CRITICAL GUARD — never pass empty ids to delete()
            if not matching_ids:
                return 0

            # Step 3: Delete by IDs
            self._collection.delete(ids=matching_ids)

        logger.debug(f"Deleted {len(matching_ids)} documents matching where={where}")
        return len(matching_ids)

    async def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their chunk IDs and return count.

        Guards against empty ID list to prevent accidental bulk deletion.
        Passing ``ids=[]`` to ChromaDB's ``collection.delete()`` wipes the
        entire collection.

        Args:
            ids: List of chunk IDs to delete. Returns 0 immediately if empty.

        Returns:
            Number of documents deleted (0 if ids is empty).

        Raises:
            RuntimeError: If the vector store is not initialized.
        """
        if not ids:
            return 0

        if not self.is_initialized:
            raise RuntimeError("Vector store not initialized. Call initialize() first.")

        async with self._lock:
            assert self._collection is not None
            self._collection.delete(ids=ids)

        logger.debug(f"Deleted {len(ids)} documents by IDs")
        return len(ids)

    async def delete_collection(self) -> None:
        """
        Delete the entire collection.

        Warning: This permanently removes all stored documents and embeddings.
        """
        if not self._client:
            return

        async with self._lock:
            try:
                assert self._client is not None
                self._client.delete_collection(self.collection_name)
                self._collection = None
                self._initialized = False
                logger.warning(f"Deleted collection: {self.collection_name}")
            except Exception as e:
                logger.error(f"Failed to delete collection: {e}")
                raise

    async def reset(self) -> None:
        """
        Reset the vector store by deleting and recreating the collection.

        Note: Embedding metadata is stored in collection metadata,
        so it will be cleared when collection is reset.
        """
        await self.delete_collection()
        self._initialized = False
        await self.initialize()

    #: Rebuild the HNSW segment when physical elements added exceed this
    #: multiple of the live count *and* the absolute slack below — i.e. only on
    #: heavy soft-delete bloat, never on a lightly-churned healthy index.
    _HEAL_BLOAT_RATIO = 2.0
    _HEAL_BLOAT_FLOOR = 1000

    def _hnsw_physical_count(self) -> int | None:
        """Physical element count of this collection's HNSW segment, or None.

        Reads ChromaDB's own SQLite (to map collection → segment dir) and the
        segment's ``index_metadata.pickle`` ``total_elements_added`` counter.
        File + read-only: it never loads the HNSW graph, so it cannot segfault
        on a corrupt index. Any failure returns None (treated as "unknown").

        Soft-deletes never shrink this counter, so ``physical >> live`` means
        the graph still holds thousands of orphaned nodes whose labels ChromaDB
        no longer maps — the desync that makes the next upsert's native resize
        segfault.
        """
        import pickle
        import sqlite3

        persist = Path(self.persist_dir)
        db = persist / "chroma.sqlite3"
        if not db.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                row = con.execute(
                    "SELECT s.id FROM segments s JOIN collections c "
                    "ON s.collection = c.id "
                    "WHERE c.name = ? AND s.scope = 'VECTOR'",
                    (self.collection_name,),
                ).fetchone()
            finally:
                con.close()
            if not row:
                return None
            pickle_path = persist / str(row[0]) / "index_metadata.pickle"
            if not pickle_path.exists():
                return None
            with open(pickle_path, "rb") as fh:
                meta = pickle.load(fh)
            tea = getattr(meta, "__dict__", {}).get("total_elements_added")
            return int(tea) if tea is not None else None
        except Exception:  # noqa: BLE001 — detection must never crash startup
            return None

    def _measured_cosine(self) -> bool | None:
        """True if the index *actually* scores by cosine distance, else False;
        None when undetermined.

        We score similarity as ``1 - distance`` (cosine), so a collection on the
        ``l2`` default returns squared-euclidean distances that map to negative
        similarity and get filtered out — vector search silently returns almost
        nothing. ChromaDB's persisted ``config_json_str`` and collection metadata
        both *lie* about the space for metadata-created collections (they report
        'l2' or a stale 'cosine' regardless of the real segment), so the only
        reliable signal is behavioral: ask ChromaDB for the distance between a
        stored vector and its nearest neighbor, then compare it to the cosine and
        squared-l2 values we compute ourselves.

        This issues a query (loads the HNSW graph), so only call it on a
        known-healthy index — after the bloat rebuild below, never before a
        bloated/corrupt index that could segfault.
        """
        import numpy as np

        if self._collection is None:
            return None
        try:
            head = self._collection.get(
                limit=1,
                include=["embeddings"],  # type: ignore[list-item]
            )
            head_embs = head.get("embeddings")
            if head_embs is None or len(head_embs) == 0:
                return None
            av = np.asarray(head_embs[0], dtype=float)
            res = self._collection.query(
                query_embeddings=[av.tolist()],
                n_results=2,
                include=["embeddings", "distances"],  # type: ignore[list-item]
            )
            res_dists = res["distances"]
            res_embs = res["embeddings"]
            if not res_dists or not res_embs or len(res_dists[0]) < 2:
                return None  # need a neighbor besides self
            dists = res_dists[0]
            embs = res_embs[0]
            bv = np.asarray(embs[1], dtype=float)
            reported = float(dists[1])
            na, nb = float(np.linalg.norm(av)), float(np.linalg.norm(bv))
            if na == 0.0 or nb == 0.0:
                return None
            cos_dist = 1.0 - float(av @ bv) / (na * nb)
            l2_sq = float(np.sum((av - bv) ** 2))
            if abs(cos_dist - l2_sq) < 1e-4:
                return None  # this pair can't distinguish the two metrics
            return abs(reported - cos_dist) <= abs(reported - l2_sq)
        except Exception:  # noqa: BLE001 — detection must never crash startup
            return None

    def _prune_orphan_segments(self) -> int:
        """Delete on-disk HNSW segment dirs no longer referenced by ChromaDB.

        Recreating a collection (the rebuild below, or a ``reset``) leaves the
        old segment's directory behind — ChromaDB drops the ``segments`` row but
        not the folder, so a stale multi-hundred-MB index lingers. This sweeps
        ``persist_dir`` for UUID-named segment dirs (identified by their HNSW
        files) whose id is absent from the live ``segments`` table and removes
        them. Read-only against SQLite; never raises.

        Returns the number of orphan directories removed.
        """
        import shutil
        import sqlite3

        persist = Path(self.persist_dir)
        db = persist / "chroma.sqlite3"
        if not db.exists():
            return 0
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                live = {row[0] for row in con.execute("SELECT id FROM segments")}
            finally:
                con.close()
        except Exception:  # noqa: BLE001 — never fail on cleanup
            return 0

        removed = 0
        for child in persist.iterdir():
            if not child.is_dir() or child.name in live:
                continue
            # Only touch real segment dirs (have an HNSW header) — never an
            # unexpected sibling folder.
            if not (child / "header.bin").exists():
                continue
            try:
                shutil.rmtree(child)
                removed += 1
                logger.info("Removed orphan vector segment dir: %s", child.name)
            except Exception as exc:  # noqa: BLE001 — never fail on cleanup
                logger.warning("Failed to remove orphan segment %s: %s", child, exc)
        return removed

    @property
    def heal_events_path(self) -> Path | None:
        """Path to the persistent heal-event audit log (``.brainpalace/``).

        ``persist_dir`` is ``<state_dir>/data/chroma_db``, so the state dir is
        two levels up. Returns ``None`` for the legacy CWD-relative default
        (``./chroma_db``) where that derivation would point outside the project.
        """
        persist = Path(self.persist_dir)
        if persist.parent.name != "data":
            return None  # legacy/non-standard layout — skip the marker
        return persist.parent.parent / STATE_SUBDIR / "heal-events.jsonl"

    def _record_heal_event(
        self, reason: str, physical: int | None, live: int, recovered: int
    ) -> None:
        """Append one heal event to ``heal-events.jsonl`` (best-effort, audit).

        The heal rebuilds to the *live* count; when the HNSW held far more
        physical slots than that, a large drop just got locked in. Persisting
        the event makes that loss auditable (surfaced in ``brainpalace status``)
        instead of scrolling past in the log. Never raises.
        """
        path = self.heal_events_path
        if path is None:
            return
        import json
        from datetime import datetime, timezone

        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "collection": self.collection_name,
            "reason": reason,
            "physical": physical,
            "live": live,
            "recovered": recovered,
            # Slots shed by the rebuild — the upper bound on what the heal lost.
            "dropped": (physical - recovered) if physical is not None else None,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except Exception as exc:  # noqa: BLE001 — auditing must never block heal
            logger.warning("Failed to record heal event to %s: %s", path, exc)

    @staticmethod
    def read_heal_events(persist_dir: str, limit: int = 50) -> dict[str, Any]:
        """Read the heal-event log for status reporting (best-effort).

        Returns ``{"count", "total_dropped", "last": <event|None>}``. Never
        raises; a missing/unparseable log yields zeroed counters.
        """
        import json

        persist = Path(persist_dir)
        if persist.parent.name != "data":
            return {"count": 0, "total_dropped": 0, "last": None}
        path = persist.parent.parent / STATE_SUBDIR / "heal-events.jsonl"
        if not path.exists():
            return {"count": 0, "total_dropped": 0, "last": None}
        events: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:  # noqa: BLE001 — skip a corrupt line
                    continue
        except Exception as exc:  # noqa: BLE001 — never fail status on the log
            logger.warning("Failed to read heal events from %s: %s", path, exc)
            return {"count": 0, "total_dropped": 0, "last": None}
        total_dropped = sum(int(e.get("dropped") or 0) for e in events)
        return {
            "count": len(events),
            "total_dropped": total_dropped,
            "last": events[-1] if events else None,
            "recent": events[-limit:],
        }

    async def heal_if_corrupt(self, batch_size: int = 500) -> int:
        """Rebuild a bloated or wrong-space HNSW index, returning vectors rebuilt.

        Repairs two faults, both detected from on-disk metadata only (never
        loading the HNSW graph, so detection is crash-safe) and fixed by pulling
        every live vector from SQLite and recreating the collection — WITHOUT
        re-embedding, zero provider calls:

        1. **Bloat / desync.** A segment that has accumulated thousands of
           orphaned nodes (a past duplicate-server write, or normal soft-delete
           churn) is a landmine: the next upsert triggers a native HNSW resize
           that segfaults the whole process with no traceback, so it can't be
           caught and the server crash-loops on every start. Detected via
           ``_hnsw_physical_count`` dwarfing the live count.
        2. **Wrong distance space.** A collection stuck on the ``l2`` default
           (``_collection_space``) returns squared-euclidean distances that our
           ``1 - distance`` cosine scoring maps to negative similarity, so vector
           search silently returns almost nothing. The rebuild forces cosine.

        Rebuilding resets the element counter and pins cosine, so a healed index
        does not re-trigger next start — no repeated rebuilds.

        Runs before any indexing upsert so the index self-heals instead of
        crashing the server. Cheap no-op when the index is healthy.

        Returns:
            Number of vectors rebuilt (0 when no repair was needed).
        """
        if not self.is_initialized or self._collection is None:
            return 0

        live = await self.get_count()
        if live == 0:
            return 0

        physical = await asyncio.to_thread(self._hnsw_physical_count)
        bloated = (
            physical is not None
            and physical >= self._HEAL_BLOAT_RATIO * live + self._HEAL_BLOAT_FLOOR
        )

        reason: str | None
        if bloated:
            reason = (
                f"bloated (HNSW holds {physical} element slots for {live} live "
                f"vectors — native resize crash risk)"
            )
        else:
            # Only probe the metric on a non-bloated index — the probe queries
            # the HNSW graph, which would segfault on a bloated/corrupt one.
            reason = (
                "wrong distance space (vector search needs cosine)"
                if await asyncio.to_thread(self._measured_cosine) is False
                else None
            )

        if reason is None:
            return 0  # healthy

        logger.warning(
            "Vector index %r needs repair: %s — rebuilding from SQLite "
            "(no re-embed)",
            self.collection_name,
            reason,
        )

        async with self._lock:
            assert self._client is not None
            collection = self._collection

            def _rebuild() -> int:
                # get() reads SQLite only — safe on a bloated/corrupt HNSW.
                data = collection.get(include=["embeddings", "documents", "metadatas"])
                ids = data["ids"]
                embs = data["embeddings"]
                docs = data.get("documents") or [""] * len(ids)
                metas = data.get("metadatas") or [None] * len(ids)
                # Preserve embedding metadata but force the cosine space — this
                # is the one chance to fix a collection stuck on the l2 default.
                keep_meta = dict(collection.metadata or {})
                keep_meta["hnsw:space"] = "cosine"

                # Recreate the collection → fresh, compact, cosine HNSW segment.
                self._client.delete_collection(self.collection_name)
                new_collection = self._client.create_collection(
                    name=self.collection_name,
                    metadata=keep_meta,
                )
                for start in range(0, len(ids), batch_size):
                    end = min(start + batch_size, len(ids))
                    new_collection.add(
                        ids=ids[start:end],
                        embeddings=embs[start:end],
                        documents=[d or "" for d in docs[start:end]],
                        metadatas=[m or {} for m in metas[start:end]],
                    )
                self._collection = new_collection
                return len(ids)

            recovered = await asyncio.to_thread(_rebuild)
            # Sweep the now-orphaned old segment dir left by the recreate.
            await asyncio.to_thread(self._prune_orphan_segments)

        # The rebuild keeps only the *live* count; if the HNSW held far more
        # physical slots, that gap was shed for good. Make the loss loud and
        # auditable rather than a single easy-to-miss INFO line.
        dropped = (physical - recovered) if physical is not None else 0
        if dropped > 0:
            logger.warning(
                "Healed vector index %r: rebuilt %d live vectors from SQLite "
                "(HNSW held %d physical slots — %d shed by the rebuild). "
                "Recorded to heal-events.jsonl; check `brainpalace status`.",
                self.collection_name,
                recovered,
                physical,
                dropped,
            )
        else:
            logger.warning(
                "Healed vector index %r: rebuilt %d live vectors from SQLite",
                self.collection_name,
                recovered,
            )
        await asyncio.to_thread(
            self._record_heal_event, reason, physical, live, recovered
        )
        return recovered

    #: Compaction trigger: at least this many dead rows AND dead >= ratio×live.
    #: Dead rows are the chunk-recovery fuel, so compaction runs only when the
    #: caller has verified the index is complete (nothing left to recover) and
    #: the bloat is heavy — a healthy store never pays.
    _COMPACT_MIN_DEAD = 5000
    _COMPACT_DEAD_RATIO = 1.0

    def _dead_row_stats(self) -> tuple[int, int] | None:
        """(dead, live) embedding-row counts from ``chroma.sqlite3``, or None.

        Read-only file probe (never loads chroma), never raises. A "dead" row
        belongs to no live segment — stranded by a past collection recreation.
        """
        path = Path(self.persist_dir) / "chroma.sqlite3"
        if not path.exists():
            return None
        import sqlite3  # noqa: PLC0415 — stdlib, probe-only

        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                total = con.execute("SELECT count(*) FROM embeddings").fetchone()[0]
                live = con.execute(
                    "SELECT count(*) FROM embeddings WHERE segment_id IN "
                    "(SELECT id FROM segments)"
                ).fetchone()[0]
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001 — probe must never crash startup
            logger.warning("dead-row probe failed for %s: %s", path, exc)
            return None
        return total - live, live

    @property
    def compact_events_path(self) -> Path | None:
        """``<state_dir>/compact-events.jsonl`` (mirrors heal_events_path)."""
        persist = Path(self.persist_dir)
        if persist.parent.name != "data":
            return None
        return persist.parent.parent / STATE_SUBDIR / "compact-events.jsonl"

    def _record_compact_event(self, event: dict[str, Any]) -> None:
        """Append one compaction event (best-effort audit, never raises)."""
        path = self.compact_events_path
        if path is None:
            return
        import json  # noqa: PLC0415
        from datetime import datetime, timezone  # noqa: PLC0415

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"ts": datetime.now(timezone.utc).isoformat(), **event}
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:  # noqa: BLE001 — auditing must never block
            logger.warning("Failed to record compact event to %s: %s", path, exc)

    async def compact_if_bloated(
        self,
        *,
        min_dead: int | None = None,
        dead_ratio: float | None = None,
        batch_size: int = 500,
    ) -> dict[str, Any] | None:
        """Reclaim dead-row bloat by rebuilding the persist dir from live data.

        Collection recreations (heal rebuilds, resets, duplicate-server stomps)
        strand the previous generation's rows in ``chroma.sqlite3`` — kept on
        purpose as chunk-recovery fuel, but after a few incidents the file
        holds several full copies of the index and SQLite never shrinks.

        This copies EVERY live collection (the sqlite file is shared, e.g. the
        memories collection) into a fresh persist dir via the public API — no
        re-embed — verifies the copy's counts, then atomically swaps it in and
        deletes the old dir. A crash mid-build leaves the old dir untouched
        (the ``.compacting`` leftover is swept on the next attempt); the swap
        itself is two renames.

        **Caller contract: run only when the index is verified complete**
        (startup self-heal found nothing missing) — compaction deletes the
        dead rows recovery would otherwise restore from.

        Returns a summary dict when compaction ran, else ``None``.
        """
        if not self.is_initialized or self._client is None:
            return None
        stats = await asyncio.to_thread(self._dead_row_stats)
        if stats is None:
            return None
        dead, live = stats
        floor = self._COMPACT_MIN_DEAD if min_dead is None else min_dead
        ratio = self._COMPACT_DEAD_RATIO if dead_ratio is None else dead_ratio
        if dead < floor or dead < ratio * live:
            return None

        logger.warning(
            "Vector store bloated: %d dead row(s) vs %d live — compacting "
            "persist dir (no re-embed)",
            dead,
            live,
        )
        async with self._lock:
            result = await asyncio.to_thread(self._compact, batch_size)
        if result is None:
            return None
        result.update({"dead_rows_reclaimed": dead, "live_rows": live})
        await asyncio.to_thread(self._record_compact_event, result)
        logger.warning(
            "Compacted vector store: reclaimed %d dead row(s), kept %d live "
            "across %d collection(s) (%s → %s bytes)",
            dead,
            live,
            result.get("collections", 0),
            f"{result.get('bytes_before', 0):,}",
            f"{result.get('bytes_after', 0):,}",
        )
        return result

    def _compact(self, batch_size: int) -> dict[str, Any] | None:
        """Build a fresh persist dir from live data and swap it in (sync).

        Must run under ``self._lock``. Returns None (old dir untouched) on any
        failure — compaction is an optimization and must never lose data.
        """
        import shutil  # noqa: PLC0415

        old_dir = Path(self.persist_dir)
        new_dir = old_dir.with_name(old_dir.name + ".compacting")
        bak_dir = old_dir.with_name(old_dir.name + ".pre-compact")
        sqlite_path = old_dir / "chroma.sqlite3"
        bytes_before = sqlite_path.stat().st_size if sqlite_path.exists() else 0

        assert self._client is not None
        try:
            # 1. Snapshot every live collection through the public API.
            snapshots: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            for coll_ref in self._client.list_collections():
                coll = self._client.get_collection(coll_ref.name)
                data = coll.get(include=["embeddings", "documents", "metadatas"])
                snapshots.append((coll.name, dict(coll.metadata or {}), data))

            # 2. Build the replacement dir (crash here leaves old dir intact).
            for leftover in (new_dir, bak_dir):
                if leftover.exists():
                    shutil.rmtree(leftover)
            new_client = chromadb.PersistentClient(
                path=str(new_dir),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
            for name, meta, data in snapshots:
                meta.setdefault("hnsw:space", "cosine")
                new_coll = new_client.create_collection(name=name, metadata=meta)
                ids = data.get("ids") or []
                embs = data.get("embeddings")
                docs = data.get("documents") or [""] * len(ids)
                metas = data.get("metadatas") or [None] * len(ids)
                for start in range(0, len(ids), batch_size):
                    end = min(start + batch_size, len(ids))
                    new_coll.add(
                        ids=ids[start:end],
                        embeddings=embs[start:end],
                        documents=[d or "" for d in docs[start:end]],
                        # Chroma rejects {} per-item metadata; None is allowed.
                        metadatas=[m if m else None for m in metas[start:end]],
                    )
                # 3. Verify before anything is swapped.
                if new_coll.count() != len(ids):
                    raise RuntimeError(
                        f"compaction verify failed for {name!r}: "
                        f"{new_coll.count()} != {len(ids)}"
                    )
        except Exception as exc:  # noqa: BLE001 — never lose data on a failure
            logger.warning("Compaction aborted (old store untouched): %s", exc)
            shutil.rmtree(new_dir, ignore_errors=True)
            return None

        # 4. Swap: old → .pre-compact, new → live path. Drop chroma's cached
        # client handles first so the re-open below binds the fresh dir.
        self._client = None
        self._collection = None
        try:
            import chromadb.api.client as _chroma_client  # noqa: PLC0415

            _chroma_client.SharedSystemClient.clear_system_cache()
        except Exception:  # noqa: BLE001 — cache shape varies across versions
            pass
        old_dir.rename(bak_dir)
        new_dir.rename(old_dir)

        # 5. Re-open on the live path and delete the bloat.
        self._client = chromadb.PersistentClient(
            path=str(old_dir),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        shutil.rmtree(bak_dir, ignore_errors=True)

        new_sqlite = old_dir / "chroma.sqlite3"
        bytes_after = new_sqlite.stat().st_size if new_sqlite.exists() else 0
        return {
            "collections": len(snapshots),
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
        }

    async def close(self) -> None:
        """
        Close the vector store connection.

        Should be called during application shutdown.
        """
        async with self._lock:
            self._collection = None
            self._client = None
            self._initialized = False
            logger.info("Vector store connection closed")


# Global singleton instance
_vector_store: VectorStoreManager | None = None


def get_vector_store() -> VectorStoreManager:
    """Get the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStoreManager()
    return _vector_store


def set_vector_store(instance: VectorStoreManager) -> None:
    """Replace the global VectorStoreManager singleton.

    Used by the server lifespan to register a manager constructed with the
    correct project-resolved persist_dir, so later get_vector_store() calls
    (e.g. from ChromaBackend) reuse it instead of building a CWD-relative one.
    """
    global _vector_store
    _vector_store = instance


async def initialize_vector_store() -> VectorStoreManager:
    """Initialize and return the global vector store instance."""
    store = get_vector_store()
    await store.initialize()
    return store
