"""Phase 130 — GitCommitChunker: commit record -> git_commit chunk."""

from __future__ import annotations

from datetime import datetime, timezone

from brainpalace_server.indexing.git_chunker import GitCommitChunker
from brainpalace_server.indexing.git_loader import CommitRecord


def _record(**over: object) -> CommitRecord:
    base = {
        "sha": "a" * 40,
        "author": "Dev Person",
        "author_email": "dev@example.com",
        "committed_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        "subject": "switch cache backend to redis",
        "body": "why: lmdb locked under concurrency",
        "files_changed": ["cache.py", "settings.py"],
        "lines_added": 40,
        "lines_deleted": 12,
    }
    base.update(over)
    return CommitRecord(**base)  # type: ignore[arg-type]


def test_one_chunk_per_commit_with_message_text() -> None:
    chunks = GitCommitChunker().chunk(_record(), repo_name="myrepo")
    assert len(chunks) == 1
    text = chunks[0].text
    assert "switch cache backend to redis" in text
    assert "lmdb locked under concurrency" in text


def test_source_type_and_id() -> None:
    chunk = GitCommitChunker().chunk(_record())[0]
    assert chunk.metadata.source_type == "git_commit"
    assert chunk.chunk_id == "git_commit:" + "a" * 40


def test_created_at_is_committed_at_for_decay() -> None:
    rec = _record()
    chunk = GitCommitChunker().chunk(rec)[0]
    assert chunk.metadata.created_at == rec.committed_at


def test_git_metadata_in_extra() -> None:
    chunk = GitCommitChunker().chunk(_record(), branch="main")[0]
    extra = chunk.metadata.extra
    assert extra["commit_sha"] == "a" * 40
    assert extra["author"] == "Dev Person"
    # ChromaDB metadata values must be scalars — stored as a newline-joined
    # string plus a count, not a list (a list fails the whole git upsert).
    assert extra["files_changed"] == "cache.py\nsettings.py"
    assert extra["files_changed_count"] == 2
    assert isinstance(extra["files_changed"], str)
    assert extra["lines_added"] == 40
    assert extra["lines_deleted"] == 12
    assert extra["branch_seen_on"] == "main"


def test_git_metadata_values_are_chroma_scalars() -> None:
    """Every metadata value must be a ChromaDB-accepted scalar — a list (e.g.
    files_changed) fails the whole git upsert with 0 commits indexed."""
    chunk = GitCommitChunker().chunk(_record(), branch="main")[0]
    for key, value in chunk.metadata.extra.items():
        assert (
            isinstance(value, (str, int, float, bool)) or value is None
        ), f"git metadata {key!r} is {type(value).__name__}, not a scalar"


def test_diff_stat_truncated() -> None:
    rec = _record(files_changed=[f"f{i}.py" for i in range(500)])
    chunk = GitCommitChunker(max_files=10).chunk(rec)[0]
    # Only the first N files rendered into the text body.
    assert chunk.text.count(".py") <= 11  # 10 files + possible elision marker
