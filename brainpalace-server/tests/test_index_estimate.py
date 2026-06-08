"""Tests for the dry-run embedding-token estimate (IndexingService.estimate_tokens)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainpalace_server.indexing.document_loader import LoadedDocument
from brainpalace_server.models import IndexRequest
from brainpalace_server.services import IndexingService


def _doc(text: str, source_type: str) -> LoadedDocument:
    return LoadedDocument(
        text=text,
        source="s",
        file_name="f",
        file_path="/p/f",
        file_size=len(text.encode()),
        metadata={"source_type": source_type},
    )


def _service(docs: list[LoadedDocument]) -> IndexingService:
    loader = MagicMock()
    loader.load_files = AsyncMock(return_value=docs)
    # storage_backend mock avoids the get_storage_backend() factory; estimate
    # never touches storage anyway.
    return IndexingService(document_loader=loader, storage_backend=MagicMock())


def _provider(provider: str, model: str) -> MagicMock:
    settings = MagicMock()
    settings.embedding.provider = provider
    settings.embedding.model = model
    return settings


@pytest.mark.asyncio
async def test_estimate_heuristic_split_and_overlap() -> None:
    svc = _service([_doc("a" * 400, "code"), _doc("b" * 400, "doc")])
    req = IndexRequest(
        folder_path=".", chunk_size=512, chunk_overlap=50, include_code=True
    )
    with patch(
        "brainpalace_server.services.indexing_service.load_provider_settings",
        return_value=_provider("ollama", "nomic-embed-text"),  # -> chars/4 heuristic
    ):
        est = await svc.estimate_tokens(req)

    assert est["files"] == 2
    assert est["code_files"] == 1
    assert est["doc_files"] == 1
    assert est["raw_tokens"] == 200  # ceil(400/4) * 2
    assert est["overlap_factor"] == round(1 + 50 / 512, 3)
    assert est["est_embedding_tokens"] == int(round(200 * (1 + 50 / 512)))
    assert est["tokenizer"].startswith("heuristic")
    assert est["approximate"] is True
    assert est["summaries_enabled"] is False


@pytest.mark.asyncio
async def test_estimate_uses_tiktoken_for_openai() -> None:
    svc = _service([_doc("hello world from brainpalace", "doc")])
    req = IndexRequest(folder_path=".", chunk_size=512, chunk_overlap=0)
    with patch(
        "brainpalace_server.services.indexing_service.load_provider_settings",
        return_value=_provider("openai", "text-embedding-3-small"),
    ):
        est = await svc.estimate_tokens(req)

    assert est["tokenizer"].startswith("tiktoken:")
    assert est["raw_tokens"] > 0
    # No overlap -> embedded equals raw.
    assert est["est_embedding_tokens"] == est["raw_tokens"]


def test_effective_include_patterns_unions_presets() -> None:
    svc = IndexingService(storage_backend=MagicMock())
    req = IndexRequest(
        folder_path=".", include_patterns=["*.md"], include_types=["python"]
    )
    with patch(
        "brainpalace_server.services.file_type_presets.resolve_file_types",
        return_value=["*.py", "*.md"],
    ):
        patterns = svc._effective_include_patterns(req)
    assert "*.md" in patterns
    assert "*.py" in patterns
    assert patterns.count("*.md") == 1  # de-duped
