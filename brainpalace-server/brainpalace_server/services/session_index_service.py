"""Phase 050 — orchestrate session ingestion into the existing index.

Resolves a project's runtime session directory, enumerates transcripts (and
their sub-agent transcripts), chunks each via :class:`SessionChunker`, dedups
against already-stored chunk ids (content-hash), embeds only the new chunks, and
upserts them into the same vector/BM25/metadata store as code+docs — tagged
``source_type="session_turn"``.

No LLM. OFF unless the project opts in (see :mod:`session_config`). Per ADR 0001
the raw JSONL stays the source-of-truth; only derived chunks are stored.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.indexing.session_chunker import SessionChunker
from brainpalace_server.indexing.session_loader import load_session

logger = logging.getLogger(__name__)


def encode_project_to_sessions_dir(project_path: str, home: Path | None = None) -> Path:
    """Map a project cwd to its Claude Code session dir.

    Claude Code stores transcripts at
    ``~/.claude/projects/<cwd-with-slashes-as-dashes>/``.
    """
    home = home or Path.home()
    encoded = project_path.replace("/", "-")
    return home / ".claude" / "projects" / encoded


class SessionIndexService:
    """Ingest session transcripts into the shared index."""

    def __init__(
        self,
        embedding_generator: Any,
        storage_backend: Any,
    ) -> None:
        self.embedding_generator = embedding_generator
        self.storage_backend = storage_backend

    async def index_session_file(
        self,
        path: str | Path,
        include_user_turns: bool = False,
        window: int = 4,
        stride: int = 2,
        origin_path: str | None = None,
    ) -> dict[str, Any]:
        """Chunk + dedup + embed + upsert a single transcript."""
        meta, turns = load_session(path)
        if origin_path is not None:
            meta.origin_path = origin_path
        chunker = SessionChunker(
            window=window, stride=stride, include_user_turns=include_user_turns
        )
        chunks = chunker.chunk(meta, turns)

        new_chunks = []
        skipped = 0
        for chunk in chunks:
            existing = await self.storage_backend.get_by_id(chunk.chunk_id)
            if existing is None:
                new_chunks.append(chunk)
            else:
                skipped += 1

        if new_chunks:
            embeddings = await self.embedding_generator.embed_chunks(new_chunks)
            await self.storage_backend.upsert_documents(
                ids=[c.chunk_id for c in new_chunks],
                embeddings=embeddings,
                documents=[c.text for c in new_chunks],
                metadatas=[c.metadata.to_dict() for c in new_chunks],
            )

        return {
            "session_id": meta.session_id,
            "is_subagent": meta.is_subagent,
            "parent_session_id": meta.parent_session_id,
            "chunks_total": len(chunks),
            "chunks_new": len(new_chunks),
            "skipped": skipped,
        }

    def _discover(self, sessions_dir: Path) -> list[Path]:
        """Top-level transcripts + sub-agent transcripts (R2)."""
        if not sessions_dir.exists():
            return []
        files = sorted(sessions_dir.glob("*.jsonl"))
        files += sorted(sessions_dir.glob("*/subagents/*.jsonl"))
        return files

    async def index_project(
        self,
        project_path: str,
        config: SessionIndexingConfig,
        home: Path | None = None,
    ) -> dict[str, Any]:
        """Index all (in-retention) transcripts for a project, if enabled."""
        summary: dict[str, Any] = {
            "enabled": config.enabled,
            "files": 0,
            "files_skipped_old": 0,
            "sessions": {},
        }
        if not config.enabled:
            return summary

        sessions_dir = (
            Path(config.sessions_dir)
            if config.sessions_dir
            else encode_project_to_sessions_dir(project_path, home=home)
        )
        files = self._discover(sessions_dir)
        cutoff = time.time() - config.retain_days * 86400

        for path in files:
            try:
                if path.stat().st_mtime < cutoff:
                    summary["files_skipped_old"] += 1
                    continue
            except OSError:
                continue
            result = await self.index_session_file(
                path,
                include_user_turns=config.include_user_turns,
                window=config.window,
                stride=config.stride,
            )
            summary["files"] += 1
            sid = result["session_id"] or str(path)
            summary["sessions"][sid] = result

        return summary
