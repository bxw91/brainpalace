"""Phase 130 — turn a :class:`CommitRecord` into a ``git_commit`` chunk.

One chunk per commit: the message (subject + body) plus a truncated diff stat,
tagged ``source_type="git_commit"`` for the existing vector + BM25 + metadata
stack — exactly like the 050 session chunker, no LLM.

``created_at`` is set to the commit's ``committed_at`` so 110 time-decay applies
to commit age for free. The chunk id is ``git_commit:<sha>`` — the sha already
content-addresses the commit, so re-ingesting an unchanged commit upserts the
same id and re-embeds nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from brainpalace_server.indexing.chunking import ChunkMetadata, TextChunk

if TYPE_CHECKING:
    from brainpalace_server.indexing.git_loader import CommitRecord

DEFAULT_MAX_FILES = 50


def _count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class GitCommitChunker:
    """Render commit records as ``git_commit`` chunks."""

    def __init__(self, max_files: int = DEFAULT_MAX_FILES) -> None:
        self.max_files = max(1, max_files)

    def _render(self, rec: CommitRecord) -> str:
        parts = [rec.subject]
        if rec.body:
            parts.append("")
            parts.append(rec.body)
        shown = rec.files_changed[: self.max_files]
        if shown:
            parts.append("")
            parts.append(
                f"Files changed (+{rec.lines_added}/-{rec.lines_deleted}):"
            )
            parts.extend(shown)
            if len(rec.files_changed) > self.max_files:
                parts.append(f"… +{len(rec.files_changed) - self.max_files} more")
        return "\n".join(parts)

    def chunk(
        self,
        rec: CommitRecord,
        repo_name: str | None = None,
        branch: str | None = None,
    ) -> list[TextChunk]:
        text = self._render(rec)
        chunk_id = f"git_commit:{rec.sha}"
        committed_iso = rec.committed_at.isoformat()

        extra: dict[str, Any] = {
            "commit_sha": rec.sha,
            "author": rec.author,
            "author_email": rec.author_email,
            "committed_at": committed_iso,
            "files_changed": rec.files_changed,
            "lines_added": rec.lines_added,
            "lines_deleted": rec.lines_deleted,
            "branch_seen_on": branch,
            "content_hash": rec.sha,
        }

        metadata = ChunkMetadata(
            chunk_id=chunk_id,
            source=repo_name or "git",
            file_name=repo_name or "git",
            chunk_index=0,
            total_chunks=1,
            source_type="git_commit",
            created_at=rec.committed_at,
            extra=extra,
        )
        return [
            TextChunk(
                chunk_id=chunk_id,
                text=text,
                source=repo_name or "git",
                chunk_index=0,
                total_chunks=1,
                token_count=_count_tokens(text),
                metadata=metadata,
            )
        ]
