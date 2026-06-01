"""Phase 060 — persist a session extraction payload across stores.

No LLM here: the payload is produced by the AI coding tool (070/080). This
service writes the derived summary/decision chunks into the shared vector store,
pushes triplets into the graph (best-effort; no-op when graph is disabled), and
maintains a git-tracked, decisions-only markdown digest (ADR 0001).

Idempotent on ``session_id``: a re-submit purges the session's prior
summary/decision chunks (so a shrinking decision list leaves no stragglers) and
rewrites its digest block.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from brainpalace_server.config import settings
from brainpalace_server.indexing.chunking import ChunkMetadata, TextChunk
from brainpalace_server.models.session_extract import (
    SessionExtraction,
    SessionExtractResult,
)
from brainpalace_server.services.session_linker import (
    apply_supersessions,
    canonicalize_entity,
    promote_decisions,
)
from brainpalace_server.services.session_triplet_types import types_for

logger = logging.getLogger(__name__)

_SUMMARY_TYPE = "session_summary"
_DECISION_TYPE = "session_decision"


def _chunk(
    chunk_id: str,
    text: str,
    source_type: str,
    payload: SessionExtraction,
    chunk_index: int,
    total: int,
    extra: dict[str, Any],
) -> TextChunk:
    base_extra: dict[str, Any] = {
        "session_id": payload.session_id,
        "branch": payload.branch,
        "started_at": payload.started_at,
    }
    base_extra.update(extra)
    meta = ChunkMetadata(
        chunk_id=chunk_id,
        source=f"session:{payload.session_id}",
        file_name=payload.session_id,
        chunk_index=chunk_index,
        total_chunks=total,
        source_type=source_type,
        extra=base_extra,
    )
    return TextChunk(
        chunk_id=chunk_id,
        text=text,
        source=f"session:{payload.session_id}",
        chunk_index=chunk_index,
        total_chunks=total,
        token_count=max(1, len(text) // 4),
        metadata=meta,
    )


def _render_digest_block(payload: SessionExtraction) -> str:
    lines = [
        f"<!-- session:{payload.session_id} -->",
        f"## Session `{payload.session_id}`"
        + (f" — {payload.started_at}" if payload.started_at else ""),
    ]
    if payload.branch:
        lines.append(f"_branch: {payload.branch}_")
    for d in payload.decisions:
        line = f"- {d.text}"
        if d.rationale:
            line += f" — _{d.rationale}_"
        if d.files:
            line += f" ({', '.join(d.files)})"
        lines.append(line)
        if d.supersedes:
            lines.append(f"  - supersedes: {d.supersedes}")
    lines.append(f"<!-- /session:{payload.session_id} -->")
    return "\n".join(lines)


def _write_digest(digest_path: Path, payload: SessionExtraction) -> bool:
    """Rewrite this session's block in the decisions digest. Idempotent."""
    begin = f"<!-- session:{payload.session_id} -->"
    end = f"<!-- /session:{payload.session_id} -->"
    block = _render_digest_block(payload)

    existing = ""
    if digest_path.exists():
        existing = digest_path.read_text(encoding="utf-8")

    if begin in existing and end in existing:
        pre = existing.split(begin)[0].rstrip("\n")
        post = existing.split(end, 1)[1].lstrip("\n")
        parts = [p for p in (pre, block, post) if p]
        new = "\n\n".join(parts) + "\n"
    else:
        header = "" if existing.strip() else "# Decisions digest\n\n"
        new = existing.rstrip("\n") + "\n\n" if existing.strip() else header
        new += block + "\n"

    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(new, encoding="utf-8")
    return True


class SessionExtractService:
    """Persist a :class:`SessionExtraction` across vector / graph / digest."""

    async def store(
        self,
        payload: SessionExtraction,
        *,
        embedder: Any,
        storage_backend: Any,
        graph_store: Any | None = None,
        digest_path: str | Path | None = None,
        memory_service: Any | None = None,
        project_root: str = "",
    ) -> SessionExtractResult:
        sid = payload.session_id

        # Idempotency: purge prior summary/decision chunks for this session.
        for stype in (_SUMMARY_TYPE, _DECISION_TYPE):
            try:
                await storage_backend.delete_by_metadata(
                    {"session_id": sid, "source_type": stype}
                )
            except Exception as exc:  # noqa: BLE001 — backend may lack the filter
                logger.debug("extract purge skipped (%s): %s", stype, exc)

        chunks: list[TextChunk] = []
        summary_id = f"{_SUMMARY_TYPE}:{sid}"
        total = 1 + len(payload.decisions)
        chunks.append(
            _chunk(
                summary_id,
                payload.summary,
                _SUMMARY_TYPE,
                payload,
                0,
                total,
                {
                    "open_threads": payload.open_threads,
                    "tools_used": payload.tools_used,
                    "files_touched": [f.path for f in payload.files_touched],
                },
            )
        )
        for i, d in enumerate(payload.decisions):
            text = d.text + (f"\nRationale: {d.rationale}" if d.rationale else "")
            chunks.append(
                _chunk(
                    f"{_DECISION_TYPE}:{sid}:{i}",
                    text,
                    _DECISION_TYPE,
                    payload,
                    i + 1,
                    total,
                    {"files": d.files, "supersedes": d.supersedes},
                )
            )

        embeddings = await embedder.embed_chunks(chunks)
        await storage_backend.upsert_documents(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata.to_dict() for c in chunks],
        )

        triplets_stored = 0
        if graph_store is not None:
            for t in payload.triplets:
                try:
                    subj_type, obj_type = types_for(t.relation)
                    # Phase 140: canonicalise file-like endpoints so the graph
                    # keeps one node per real file.
                    subj = canonicalize_entity(t.subject, project_root)
                    obj = canonicalize_entity(t.object, project_root)
                    if graph_store.add_triplet(
                        subj,
                        t.relation,
                        obj,
                        subject_type=subj_type,
                        object_type=obj_type,
                        source_chunk_id=summary_id,
                    ):
                        triplets_stored += 1
                except Exception as exc:  # noqa: BLE001 — graph is best-effort
                    logger.debug("add_triplet failed: %s", exc)

            # Phase 140: close superseded decisions' stale facts (temporal
            # backend only; preserves supersedes history). Best-effort.
            try:
                n = apply_supersessions(payload, graph_store, project_root)
                if n:
                    logger.debug("supersession closed facts for %d decision(s)", n)
            except Exception as exc:  # noqa: BLE001
                logger.debug("apply_supersessions failed: %s", exc)

        # Phase 140: promote durable decisions into curated memory (030).
        if memory_service is not None and getattr(
            settings, "BRAINPALACE_PROMOTE_DECISIONS", True
        ):
            try:
                promoted = await promote_decisions(payload, memory_service)
                if promoted:
                    logger.debug("promoted %d decision(s) to curated memory", promoted)
            except Exception as exc:  # noqa: BLE001
                logger.debug("promote_decisions failed: %s", exc)

        digest_updated = False
        if digest_path and payload.decisions:
            try:
                digest_updated = _write_digest(Path(digest_path), payload)
            except OSError as exc:
                logger.warning("decisions digest write failed: %s", exc)

        return SessionExtractResult(
            session_id=sid,
            summary_chunks=1,
            decision_chunks=len(payload.decisions),
            triplets_stored=triplets_stored,
            digest_updated=digest_updated,
        )
