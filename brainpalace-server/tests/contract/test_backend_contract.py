"""Contract tests for StorageBackendProtocol behavior consistency.

These tests validate that all storage backends honor the same protocol-level
behavior, regardless of implementation details. The focus is on observable
contract guarantees: counts, search result structure, normalization, and
embedding metadata compatibility.
"""

from __future__ import annotations

from typing import Any

import pytest
from llama_index.core.schema import TextNode

from brainpalace_server.providers.exceptions import ProviderMismatchError
from brainpalace_server.storage.chroma.backend import ChromaBackend
from brainpalace_server.storage.protocol import EmbeddingMetadata, SearchResult

pytestmark = pytest.mark.asyncio

BASE_EMBEDDING = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

VECTOR_DOCS = [
    (
        "doc-1",
        "Python programming basics",
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ),
    (
        "doc-2",
        "JavaScript development guide",
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ),
    (
        "doc-3",
        "Rust systems programming",
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ),
]

QUERY_EMBEDDING = [0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _default_metadata(index: int) -> dict[str, Any]:
    return {"source_type": "doc", "sequence": index}


def _build_bm25_index_if_needed(
    storage_backend: Any,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    if not isinstance(storage_backend, ChromaBackend):
        return

    nodes = [
        TextNode(text=document, id_=chunk_id, metadata=metadata)
        for chunk_id, document, metadata in zip(ids, documents, metadatas, strict=True)
    ]
    storage_backend.bm25_manager.build_index(nodes)


async def _upsert_documents(
    storage_backend: Any,
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> int:
    return await storage_backend.upsert_documents(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )


class TestStorageBackendContract:
    """Contract tests for StorageBackendProtocol methods."""

    async def test_is_initialized(self, storage_backend: Any) -> None:
        assert storage_backend.is_initialized is True

    async def test_upsert_returns_count(self, storage_backend: Any) -> None:
        ids = ["doc-1", "doc-2", "doc-3"]
        documents = ["doc 1", "doc 2", "doc 3"]
        embeddings = [BASE_EMBEDDING] * 3
        metadatas = [_default_metadata(i) for i in range(3)]

        count = await _upsert_documents(
            storage_backend, ids, documents, embeddings, metadatas
        )

        assert count == 3

    async def test_upsert_updates_existing(self, storage_backend: Any) -> None:
        ids = ["doc-1"]
        embeddings = [BASE_EMBEDDING]
        metadatas = [_default_metadata(1)]

        await _upsert_documents(
            storage_backend, ids, ["original"], embeddings, metadatas
        )
        await _upsert_documents(
            storage_backend, ids, ["updated"], embeddings, metadatas
        )

        count = await storage_backend.get_count()
        assert count == 1

    async def test_vector_search_returns_search_results(
        self, storage_backend: Any
    ) -> None:
        ids = [doc_id for doc_id, _, _ in VECTOR_DOCS]
        documents = [text for _, text, _ in VECTOR_DOCS]
        embeddings = [embedding for _, _, embedding in VECTOR_DOCS]
        metadatas = [_default_metadata(i) for i in range(len(ids))]

        await _upsert_documents(storage_backend, ids, documents, embeddings, metadatas)

        results = await storage_backend.vector_search(
            query_embedding=QUERY_EMBEDDING,
            top_k=3,
            similarity_threshold=0.0,
        )

        assert results
        assert all(isinstance(result, SearchResult) for result in results)
        assert results[0].chunk_id == "doc-1"
        assert all(0.0 <= result.score <= 1.0 for result in results)
        assert all(result.text for result in results)

    async def test_keyword_search_returns_search_results(
        self, storage_backend: Any
    ) -> None:
        ids = [doc_id for doc_id, _, _ in VECTOR_DOCS]
        documents = [text for _, text, _ in VECTOR_DOCS]
        embeddings = [embedding for _, _, embedding in VECTOR_DOCS]
        metadatas = [_default_metadata(i) for i in range(len(ids))]

        await _upsert_documents(storage_backend, ids, documents, embeddings, metadatas)
        _build_bm25_index_if_needed(storage_backend, ids, documents, metadatas)

        results = await storage_backend.keyword_search(query="Python", top_k=5)

        assert results
        assert all(isinstance(result, SearchResult) for result in results)
        assert all(0.0 <= result.score <= 1.0 for result in results)

    async def test_get_count_empty(self, storage_backend: Any) -> None:
        count = await storage_backend.get_count()
        assert count == 0

    async def test_get_count_after_upsert(self, storage_backend: Any) -> None:
        ids = ["doc-1", "doc-2"]
        documents = ["alpha", "beta"]
        embeddings = [BASE_EMBEDDING, BASE_EMBEDDING]
        metadatas = [_default_metadata(i) for i in range(2)]

        await _upsert_documents(storage_backend, ids, documents, embeddings, metadatas)

        count = await storage_backend.get_count()
        assert count == 2

    async def test_get_by_id_found(self, storage_backend: Any) -> None:
        await _upsert_documents(
            storage_backend,
            ["test-id-1"],
            ["stored text"],
            [BASE_EMBEDDING],
            [_default_metadata(1)],
        )

        result = await storage_backend.get_by_id("test-id-1")

        assert result is not None
        assert "text" in result

    async def test_get_by_id_not_found(self, storage_backend: Any) -> None:
        result = await storage_backend.get_by_id("nonexistent")
        assert result is None

    async def test_reset_clears_all_data(self, storage_backend: Any) -> None:
        ids = ["doc-1", "doc-2"]
        documents = ["alpha", "beta"]
        embeddings = [BASE_EMBEDDING, BASE_EMBEDDING]
        metadatas = [_default_metadata(i) for i in range(2)]

        await _upsert_documents(storage_backend, ids, documents, embeddings, metadatas)
        await storage_backend.reset()

        count = await storage_backend.get_count()
        assert count == 0

    async def test_embedding_metadata_initially_none(
        self, storage_backend: Any
    ) -> None:
        metadata = await storage_backend.get_embedding_metadata()

        if metadata is not None:
            assert isinstance(metadata, EmbeddingMetadata)

    async def test_set_and_get_embedding_metadata(self, storage_backend: Any) -> None:
        await storage_backend.set_embedding_metadata(
            provider="openai",
            model="text-embedding-3-large",
            dimensions=8,
        )

        metadata = await storage_backend.get_embedding_metadata()

        assert metadata is not None
        assert metadata.provider == "openai"
        assert metadata.model == "text-embedding-3-large"
        assert metadata.dimensions == 8

    async def test_validate_embedding_compatibility_passes(
        self, storage_backend: Any
    ) -> None:
        metadata = EmbeddingMetadata(
            provider="openai", model="text-embedding-3-large", dimensions=8
        )

        storage_backend.validate_embedding_compatibility(
            provider="openai",
            model="text-embedding-3-large",
            dimensions=8,
            stored_metadata=metadata,
        )

    async def test_validate_embedding_compatibility_fails_dimension(
        self, storage_backend: Any
    ) -> None:
        metadata = EmbeddingMetadata(
            provider="openai", model="text-embedding-3-large", dimensions=8
        )

        with pytest.raises(ProviderMismatchError):
            storage_backend.validate_embedding_compatibility(
                provider="openai",
                model="text-embedding-3-large",
                dimensions=9,
                stored_metadata=metadata,
            )

    # Methods DocumentIngestService (POST /ingest/text) requires on the live
    # backend. The service was written against the VectorStoreManager facade,
    # so every real StorageBackendProtocol impl must expose them or ingest
    # 500s. Parametrized over both backends (postgres skips without
    # DATABASE_URL).
    async def test_get_existing_ids_returns_only_present(
        self, storage_backend: Any
    ) -> None:
        await _upsert_documents(
            storage_backend,
            ["present-1", "present-2"],
            ["a", "b"],
            [BASE_EMBEDDING, BASE_EMBEDDING],
            [_default_metadata(1), _default_metadata(2)],
        )

        existing = await storage_backend.get_existing_ids(
            ["present-1", "present-2", "absent-x"]
        )

        assert existing == {"present-1", "present-2"}

    async def test_get_existing_ids_empty_input(self, storage_backend: Any) -> None:
        assert await storage_backend.get_existing_ids([]) == set()

    async def test_get_ids_by_where_filters_by_metadata(
        self, storage_backend: Any
    ) -> None:
        await _upsert_documents(
            storage_backend,
            ["ing-1", "other-1"],
            ["shared body", "unrelated"],
            [BASE_EMBEDDING, BASE_EMBEDDING],
            [
                {"source_type": "ingest", "source_id": "s1"},
                {"source_type": "doc", "source_id": "s1"},
            ],
        )

        ids = await storage_backend.get_ids_by_where(
            {"$and": [{"source_type": "ingest"}, {"source_id": "s1"}]}
        )

        assert ids == {"ing-1"}

    async def test_get_by_id_embedding_round_trips_through_upsert(
        self, storage_backend: Any
    ) -> None:
        # The embed-frugal keep-and-refresh path reads row["embedding"] and
        # re-upserts it verbatim (no re-embed). The stored vector must come
        # back in a form the SAME backend's upsert accepts — list (postgres)
        # or ndarray (chroma). This is exactly what 500'd on postgres, where
        # get_by_id returned no embedding at all.
        await _upsert_documents(
            storage_backend,
            ["emb-1"],
            ["body"],
            [BASE_EMBEDDING],
            [_default_metadata(1)],
        )

        row = await storage_backend.get_by_id("emb-1")
        assert row is not None
        assert row["embedding"] is not None
        assert len(row["embedding"]) == len(BASE_EMBEDDING)

        # Re-upsert the stored embedding unchanged (the refresh) must not raise.
        await _upsert_documents(
            storage_backend,
            ["emb-1"],
            ["body refreshed"],
            [row["embedding"]],
            [_default_metadata(2)],
        )
        refreshed = await storage_backend.get_by_id("emb-1")
        assert refreshed is not None
        assert refreshed["text"] == "body refreshed"
