"""Unit tests — text_language lives on the typed ChunkMetadata field, not in extra.

Covers:
* ChunkMetadata direct attribute access and to_dict() round-trip.
* ContextAwareChunker: typed field populated, key absent from extra.
* CodeChunk.create / CodeChunker: typed field populated, key absent from extra.
"""

from __future__ import annotations

import pytest

from brainpalace_server.indexing.chunking import (
    ChunkMetadata,
    CodeChunk,
    CodeChunker,
    ContextAwareChunker,
)
from brainpalace_server.indexing.document_loader import LoadedDocument

# ---------------------------------------------------------------------------
# ChunkMetadata — direct field tests
# ---------------------------------------------------------------------------


def test_code_chunk_metadata_has_no_summary_fields():
    """Code-chunk summarization removed: section_summary metadata is gone."""
    md = ChunkMetadata(
        chunk_id="c1",
        source="x.py",
        file_name="x.py",
        chunk_index=0,
        total_chunks=1,
        source_type="code",
    )
    assert not hasattr(md, "section_summary")
    assert not hasattr(md, "prev_section_summary")
    assert "section_summary" not in md.to_dict()


def test_text_language_defaults_none_and_serializes():
    m = ChunkMetadata(
        chunk_id="chunk_abc123",
        source="f.md",
        file_name="f.md",
        chunk_index=0,
        total_chunks=1,
        source_type="doc",
    )
    assert m.text_language is None
    m.text_language = "hr"
    assert m.to_dict()["text_language"] == "hr"


def test_text_language_not_in_extra_when_set_via_typed_field():
    """Setting text_language via the typed field must not duplicate it in extra."""
    m = ChunkMetadata(
        chunk_id="chunk_xyz",
        source="f.md",
        file_name="f.md",
        chunk_index=0,
        total_chunks=1,
        source_type="doc",
        text_language="hr",
    )
    assert m.text_language == "hr"
    assert "text_language" not in m.extra
    d = m.to_dict()
    assert d["text_language"] == "hr"


# ---------------------------------------------------------------------------
# ContextAwareChunker — doc chunker path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_doc_chunker_text_language_on_typed_field_not_extra():
    """Doc chunks carry text_language on the typed slot, not in extra."""
    text = "Hello world. " * 30  # enough to chunk
    doc = LoadedDocument(
        text=text,
        source="sample.md",
        file_name="sample.md",
        file_path="sample.md",
        file_size=len(text),
        metadata={
            "language": "markdown",
            "content_type": "document",
            "text_language": "hr",
        },
    )

    chunker = ContextAwareChunker()
    chunks = await chunker.chunk_single_document(doc)

    assert chunks, "Expected at least one chunk"
    for chunk in chunks:
        assert chunk.metadata.text_language == "hr", (
            "Expected typed field text_language='hr', "
            f"got {chunk.metadata.text_language!r}"
        )
        assert "text_language" not in chunk.metadata.extra, (
            "text_language must not appear in extra; "
            f"extra keys: {list(chunk.metadata.extra)}"
        )
        # to_dict() output still correct
        assert chunk.metadata.to_dict()["text_language"] == "hr"


@pytest.mark.asyncio
async def test_doc_chunker_text_language_none_when_absent():
    """No text_language in metadata → typed field is None, key absent from to_dict."""
    text = "Hello world. " * 30
    doc = LoadedDocument(
        text=text,
        source="sample.md",
        file_name="sample.md",
        file_path="sample.md",
        file_size=len(text),
        metadata={"language": "markdown"},
    )

    chunker = ContextAwareChunker()
    chunks = await chunker.chunk_single_document(doc)

    assert chunks
    for chunk in chunks:
        assert chunk.metadata.text_language is None
        assert "text_language" not in chunk.metadata.extra
        assert "text_language" not in chunk.metadata.to_dict()


# ---------------------------------------------------------------------------
# CodeChunk.create — code chunker path
# ---------------------------------------------------------------------------


def test_code_chunk_create_text_language_on_typed_field():
    """CodeChunk.create() stores text_language on the typed field, not in extra."""
    chunk = CodeChunk.create(
        chunk_id="chunk_code01",
        text="def add(a, b): return a + b",
        source="mod.py",
        language="python",
        chunk_index=0,
        total_chunks=1,
        token_count=10,
        text_language="code",
        extra={"source_type": "code", "language": "python"},
    )
    assert chunk.metadata.text_language == "code"
    assert "text_language" not in chunk.metadata.extra
    assert chunk.metadata.to_dict()["text_language"] == "code"


def test_code_chunk_create_extra_stripped_of_text_language():
    """Simulate the fixed call-site: extra does NOT contain text_language."""
    raw_meta = {"source_type": "code", "language": "python", "other_key": "val"}
    doc_extra = {k: v for k, v in raw_meta.items() if k != "text_language"}

    chunk = CodeChunk.create(
        chunk_id="chunk_code02",
        text="x = 1",
        source="script.py",
        language="python",
        chunk_index=0,
        total_chunks=1,
        token_count=3,
        text_language="code",
        extra=doc_extra,
    )
    assert chunk.metadata.text_language == "code"
    assert "text_language" not in chunk.metadata.extra
    assert chunk.metadata.to_dict()["text_language"] == "code"


@pytest.mark.asyncio
async def test_code_chunker_text_language_on_typed_field_not_extra():
    """CodeChunker stamps text_language on typed field when present in doc metadata."""
    code = (
        "def hello(name):\n"
        "    return f'Hello, {name}!'\n"
        "\n" + ("# padding\n" * 20) + "\nclass Greeter:\n"
        "    def greet(self, name):\n"
        "        return f'Hi, {name}!'\n"
    )
    doc = LoadedDocument(
        text=code,
        source="mod.py",
        file_name="mod.py",
        file_path="mod.py",
        file_size=len(code),
        metadata={
            "source_type": "code",
            "language": "python",
            "text_language": "code",
        },
    )

    chunker = CodeChunker(language="python", chunk_lines=5, max_chars=200)
    chunks = await chunker.chunk_code_document(doc)

    assert chunks, "Expected at least one code chunk"
    for chunk in chunks:
        assert chunk.metadata.text_language == "code", (
            "Expected typed field text_language='code', "
            f"got {chunk.metadata.text_language!r}"
        )
        assert "text_language" not in chunk.metadata.extra, (
            "text_language must not appear in extra; "
            f"extra keys: {list(chunk.metadata.extra)}"
        )
        assert chunk.metadata.to_dict()["text_language"] == "code"
