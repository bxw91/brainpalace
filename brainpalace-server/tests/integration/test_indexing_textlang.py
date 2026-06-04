"""Integration test — text_language stamped on chunks during indexing.

Task 11: verifies that IndexingService stamps text_language on document
and code chunks before they reach storage, so the BM25 manager can pick
the right per-language analyzer.

Strategy
--------
* Real DocumentLoader + real chunkers (ContextAwareChunker, CodeChunker).
* Mocked storage backend, embedding generator, BM25 build, graph manager.
* load_bm25_config() is patched to return BM25Config(detect=True, language="en"),
  so Croatian prose is detected as "hr" and code gets "code".
* We capture the ``metadatas`` list passed to
  ``storage_backend.upsert_documents`` and inspect each chunk's text_language.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainpalace_server.config.bm25_config import BM25Config
from brainpalace_server.models import IndexRequest
from brainpalace_server.services.indexing_service import IndexingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage() -> AsyncMock:
    """Minimal mock storage backend."""
    storage = AsyncMock()
    storage.is_initialized = True
    storage.initialize = AsyncMock()
    storage.get_count = AsyncMock(return_value=0)
    storage.get_embedding_metadata = AsyncMock(return_value=None)
    storage.set_embedding_metadata = AsyncMock()
    storage.upsert_documents = AsyncMock()
    storage.delete_by_ids = AsyncMock(return_value=0)
    storage.get_by_id = AsyncMock(return_value=None)
    storage.validate_embedding_compatibility = MagicMock()
    return storage


def _make_embedding_gen() -> MagicMock:
    """Mock embedding generator — returns zero vectors."""
    gen = MagicMock()
    gen.get_embedding_dimensions = MagicMock(return_value=1536)

    async def _embed(chunks: list, cb: Any = None) -> list:
        return [[0.0] * 1536 for _ in chunks]

    gen.embed_chunks = _embed
    return gen


def _make_bm25() -> MagicMock:
    """Mock BM25 manager — build_index is a no-op."""
    mgr = MagicMock()
    mgr.build_index = MagicMock()
    return mgr


def _make_graph() -> MagicMock:
    """Mock graph index manager."""
    mgr = MagicMock()
    mgr.get_status = MagicMock(
        return_value=MagicMock(
            enabled=False,
            initialized=False,
            entity_count=0,
            relationship_count=0,
            store_type="none",
        )
    )
    return mgr


def _build_service(storage: AsyncMock) -> IndexingService:
    """Build an IndexingService with real loader + chunkers, mocked deps."""
    from brainpalace_server.indexing.document_loader import DocumentLoader

    return IndexingService(
        storage_backend=storage,
        document_loader=DocumentLoader(),
        # chunker=None → service instantiates ContextAwareChunker internally
        embedding_generator=_make_embedding_gen(),
        bm25_manager=_make_bm25(),
        graph_index_manager=_make_graph(),
        manifest_tracker=None,
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_language_stamped_on_doc_and_code_chunks(tmp_path: Path) -> None:
    """text_language == 'hr' for Croatian doc chunks, 'code' for Python chunks."""

    # --- 1. Create test files ---
    hr_text = (
        "Naručivanje termina kod liječnika obiteljske medicine. "
        "Pregled je sutra ujutro. Molimo javite se na recepciji."
    )
    (tmp_path / "note_hr.md").write_text(hr_text, encoding="utf-8")
    (tmp_path / "mod.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )

    # --- 2. Build service & patch load_bm25_config ---
    storage = _make_storage()
    service = _build_service(storage)

    detect_cfg = BM25Config(detect=True, language="en", detect_min_confidence=0.4)

    captured_metadatas: list[dict] = []

    async def _capture_upsert(
        ids: list,
        embeddings: list,
        documents: list,
        metadatas: list,
    ) -> None:
        captured_metadatas.extend(metadatas)

    storage.upsert_documents = AsyncMock(side_effect=_capture_upsert)

    with patch(
        "brainpalace_server.services.indexing_service.load_bm25_config",
        return_value=detect_cfg,
    ):
        request = IndexRequest(
            folder_path=str(tmp_path),
            include_code=True,
            recursive=False,
            force=True,
        )
        await service._run_indexing_pipeline(request, "job_test_textlang")

    # --- 3. Verify text_language on each chunk ---
    assert captured_metadatas, "No chunks were stored — check document loading"

    doc_langs = [
        m["text_language"]
        for m in captured_metadatas
        if m.get("source", "").endswith("note_hr.md")
    ]
    code_langs = [
        m["text_language"]
        for m in captured_metadatas
        if m.get("source", "").endswith("mod.py")
    ]

    assert doc_langs, "No chunks found for note_hr.md"
    assert code_langs, "No chunks found for mod.py"

    # Croatian doc must be detected as "hr" (detect=True, confidence≥0.4)
    assert all(
        lang == "hr" for lang in doc_langs
    ), f"Expected 'hr' for all note_hr.md chunks, got: {doc_langs}"

    # Python code must always get "code"
    assert all(
        lang == "code" for lang in code_langs
    ), f"Expected 'code' for all mod.py chunks, got: {code_langs}"
