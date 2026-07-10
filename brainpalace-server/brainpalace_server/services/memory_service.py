"""Curated memory namespace service (Phase 030).

The **markdown file is the source of truth** (ADR 0001): a git-tracked,
human-editable, capped list of facts. A Chroma collection mirrors it as a
rebuildable shadow index. Every mutation writes the markdown first, then syncs
the index; ``rebuild_from_markdown`` reconstructs the index from the markdown
alone (the ADR 0001 disaster-recovery guarantee).

Markdown shape (round-tripped by the parser)::

    # BrainPalace Memory

    ## Environment
    - staging url is staging.example.com <!-- ab:id=mem_1a2b3c4d tags=infra \
origin=user conf=1.0 created=2026-... last_ref= obsoleted= superseded_by= -->

Entries are ``- <text> <!-- ab:... -->`` list items under ``## <section>``
headers. Unknown lines are preserved so hand-edits survive.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from brainpalace_server.config.settings import settings
from brainpalace_server.models.memory import (
    DEFAULT_SECTION,
    Memory,
    MemoryHit,
)

if TYPE_CHECKING:
    from brainpalace_server.indexing import EmbeddingGenerator
    from brainpalace_server.storage.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)

_HEADER = "# BrainPalace Memory"
_TAG_RE = re.compile(r"<!--\s*ab:(?P<body>.*?)\s*-->\s*$")
_ENTRY_RE = re.compile(r"^\s*-\s+(?P<text>.*?)\s*<!--\s*ab:(?P<body>.*?)\s*-->\s*$")
_SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return "mem_" + secrets.token_hex(4)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class MemoryDuplicateError(ValueError):
    """Raised when a near-duplicate memory is added."""


class MemoryCapError(ValueError):
    """Raised when adding a memory would exceed the markdown char cap."""


class MemoryNotFoundError(KeyError):
    """Raised when a memory id is not found."""


def _parse_tag(body: str) -> dict[str, str]:
    """Parse ``k=v k=v`` from a tag body (values may be empty)."""
    out: dict[str, str] = {}
    for token in body.split():
        if "=" in token:
            k, _, v = token.partition("=")
            out[k] = v
    return out


class MemoryService:
    """Owns the markdown memory file and its Chroma shadow index."""

    def __init__(
        self,
        path: str | Path,
        vector_store: VectorStoreManager | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        char_cap: int | None = None,
    ) -> None:
        self.path = Path(path)
        self._vector_store = vector_store
        self._embeddings = embedding_generator
        self.char_cap = char_cap if char_cap is not None else settings.MEMORY_CHAR_CAP
        self._lock = asyncio.Lock()

    # ----- markdown source of truth -------------------------------------

    def load(self) -> list[Memory]:
        """Parse the markdown file into Memory entries (empty if no file)."""
        if not self.path.exists():
            return []
        memories: list[Memory] = []
        section = DEFAULT_SECTION
        for line in self.path.read_text(encoding="utf-8").splitlines():
            sm = _SECTION_RE.match(line)
            if sm:
                section = sm.group("name").strip()
                continue
            em = _ENTRY_RE.match(line)
            if not em:
                continue
            tag = _parse_tag(em.group("body"))
            mid = tag.get("id")
            if not mid:
                continue
            tags = [t for t in tag.get("tags", "").split(",") if t]
            try:
                conf = float(tag.get("conf", "1.0") or 1.0)
            except ValueError:
                conf = 1.0
            memories.append(
                Memory(
                    id=mid,
                    text=em.group("text").strip(),
                    section=section,
                    tags=tags,
                    origin=tag.get("origin") or "user",
                    sensitivity=tag.get("sensitivity") or "normal",
                    confidence=conf,
                    created_at=tag.get("created") or _now_iso(),
                    last_referenced_at=tag.get("last_ref") or None,
                    obsoleted_at=tag.get("obsoleted") or None,
                    superseded_by=tag.get("superseded_by") or None,
                )
            )
        return memories

    def _render(self, memories: list[Memory]) -> str:
        """Render entries back to markdown, grouped by section."""
        lines = [_HEADER, ""]
        by_section: dict[str, list[Memory]] = {}
        for m in memories:
            by_section.setdefault(m.section, []).append(m)
        for section in by_section:
            lines.append(f"## {section}")
            for m in by_section[section]:
                tagbody = (
                    f"ab:id={m.id} tags={','.join(m.tags)} origin={m.origin} "
                    f"sensitivity={m.sensitivity} "
                    f"conf={m.confidence} created={m.created_at} "
                    f"last_ref={m.last_referenced_at or ''} "
                    f"obsoleted={m.obsoleted_at or ''} "
                    f"superseded_by={m.superseded_by or ''}"
                )
                lines.append(f"- {m.text} <!-- {tagbody} -->")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _save(self, memories: list[Memory]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self._render(memories), encoding="utf-8")

    def char_count(self) -> int:
        return len(self.path.read_text(encoding="utf-8")) if self.path.exists() else 0

    # ----- eviction --------------------------------------------------------

    _EVICTABLE_PREFIX = "session:"

    def _is_evictable(self, m: Memory) -> bool:
        """Only active, auto-promoted (origin=session:*) entries may be evicted."""
        return m.is_active and (m.origin or "").startswith(self._EVICTABLE_PREFIX)

    def _eviction_order(self, memories: list[Memory]) -> list[Memory]:
        """Evictable entries, worst-first: oldest ref, then lowest confidence."""
        evictable = [m for m in memories if self._is_evictable(m)]
        return sorted(
            evictable,
            key=lambda m: (m.last_referenced_at or m.created_at, m.confidence),
        )

    # ----- mutations -----------------------------------------------------

    async def add(
        self,
        text: str,
        section: str = DEFAULT_SECTION,
        tags: list[str] | None = None,
        origin: str = "user",
        confidence: float = 1.0,
        sensitivity: str = "normal",
        *,
        reclaim: bool = False,
        supersedes: str | None = None,
    ) -> Memory:
        async with self._lock:
            memories = self.load()
            norm = _norm(text)
            for m in memories:
                if m.is_active and (_norm(m.text) == norm or norm in _norm(m.text)):
                    raise MemoryDuplicateError(
                        f"near-duplicate of existing memory {m.id!r}"
                    )

            mem = Memory(
                id=_new_id(),
                text=text.strip(),
                section=section.strip() or DEFAULT_SECTION,
                tags=tags or [],
                origin=origin,
                confidence=confidence,
                sensitivity=sensitivity,
            )

            # Reclaim DELETES (physically removes) entries so the file shrinks;
            # obsoleting would keep them in _render output and not free cap.
            removed_ids: set[str] = set()
            if reclaim and supersedes:
                target = self._match_superseded(memories, supersedes)
                if target is not None:
                    removed_ids.add(target.id)

            # Write-time semantic dedupe (embeddings-only; independent of reclaim).
            # A strong match means the user is re-asserting an existing fact — the new
            # entry supersedes the old (newest wins), so drop the old before insert.
            dupe = await self._find_semantic_supersede(text, memories)
            if dupe is not None:
                removed_ids.add(dupe.id)

            def _persisted() -> list[Memory]:
                return [m for m in memories if m.id not in removed_ids]

            candidate = self._render(_persisted() + [mem])
            if len(candidate) > self.char_cap:
                if not reclaim:
                    raise MemoryCapError(
                        f"memory file would exceed cap ({len(candidate)} > "
                        f"{self.char_cap}); obsolete or consolidate entries first"
                    )
                for victim in self._eviction_order(_persisted()):
                    removed_ids.add(victim.id)
                    candidate = self._render(_persisted() + [mem])
                    if len(candidate) <= self.char_cap:
                        break
                if len(candidate) > self.char_cap:
                    raise MemoryCapError(
                        f"memory file would exceed cap ({len(candidate)} > "
                        f"{self.char_cap}) even after evicting all evictable "
                        "entries; curate manual facts"
                    )

            final = _persisted() + [mem]
            self._save(final)
            if removed_ids:
                await self._delete_from_index(list(removed_ids))
            await self._sync_one(mem)
            return mem

    def _match_superseded(
        self, memories: list[Memory], supersedes: str
    ) -> Memory | None:
        """Find an active session-decision entry whose decision-text matches.

        Promoted decisions are stored as ``"<text> — <rationale>"``; ``supersedes``
        holds the prior decision's ``text``. Match the pre-``—`` segment by EXACT
        normalized equality — a substring match risks obsoleting the wrong entry.
        """
        want = _norm(supersedes)
        for m in memories:
            if not m.is_active or "session-decision" not in m.tags:
                continue
            if _norm(m.text.split(" — ")[0]) == want:
                return m
        return None

    async def _find_semantic_supersede(
        self, text: str, memories: list[Memory]
    ) -> Memory | None:
        """Embeddings-only near-duplicate detection for write-time curation.

        Returns the active entry the new text should supersede (top embedding match
        at or above MEMORY_DEDUPE_THRESHOLD), or None. No-op when the shadow index or
        embeddings are unavailable — the markdown remains source of truth (ADR 0001)."""
        if self._vector_store is None or self._embeddings is None:
            return None
        threshold = float(getattr(settings, "MEMORY_DEDUPE_THRESHOLD", 0.92))
        try:
            emb = await self._embeddings.embed_query(text)
            results = await self._vector_store.similarity_search(
                query_embedding=emb,
                top_k=1,
                similarity_threshold=threshold,
            )
        except Exception as exc:  # noqa: BLE001 — dedupe is best-effort, never fatal
            logger.warning("write-time dedupe search failed: %s", exc)
            return None
        if not results or results[0].score < threshold:
            return None
        mid = results[0].metadata.get("memory_id", results[0].chunk_id)
        for m in memories:
            if m.id == mid and m.is_active:
                return m
        return None

    async def obsolete(
        self, memory_id: str, superseded_by: str | None = None
    ) -> Memory:
        async with self._lock:
            memories = self.load()
            target = self._find(memories, memory_id)
            target.obsoleted_at = _now_iso()
            target.superseded_by = superseded_by
            self._save(memories)
            await self._delete_from_index([memory_id])
            return target

    async def delete(self, memory_id: str) -> None:
        async with self._lock:
            memories = self.load()
            self._find(memories, memory_id)  # raises if missing
            remaining = [m for m in memories if m.id != memory_id]
            self._save(remaining)
            await self._delete_from_index([memory_id])

    def _find(self, memories: list[Memory], memory_id: str) -> Memory:
        for m in memories:
            if m.id == memory_id:
                return m
        raise MemoryNotFoundError(memory_id)

    # ----- chroma shadow index ------------------------------------------

    async def _sync_one(self, mem: Memory) -> None:
        # Best-effort: the markdown is the source of truth (ADR 0001), so a
        # write must never fail just because the index/embeddings are down.
        # The shadow index is rebuildable via rebuild_from_markdown().
        if self._vector_store is None or self._embeddings is None:
            return
        try:
            emb = await self._embeddings.embed_text(mem.text)
            await self._vector_store.upsert_documents(
                ids=[mem.id],
                embeddings=[emb],
                documents=[mem.text],
                metadatas=[mem.to_metadata()],
            )
        except Exception as exc:  # noqa: BLE001 — index is rebuildable
            logger.warning("memory index sync failed for %s: %s", mem.id, exc)

    async def _delete_from_index(self, ids: list[str]) -> None:
        if self._vector_store is None:
            return
        try:
            await self._vector_store.delete_by_ids(ids)
        except (
            Exception
        ) as exc:  # noqa: BLE001 — index is rebuildable; don't fail the write
            logger.warning("memory index delete failed for %s: %s", ids, exc)

    async def rebuild_from_markdown(self) -> int:
        """Reconstruct the shadow index from the markdown alone (ADR 0001)."""
        if self._vector_store is None or self._embeddings is None:
            return 0
        memories = [m for m in self.load() if m.is_active]
        existing = self.load()
        if existing:
            await self._delete_from_index([m.id for m in existing])
        count = 0
        for mem in memories:
            await self._sync_one(mem)
            count += 1
        logger.info("rebuilt memory index from markdown: %d entries", count)
        return count

    # ----- recall --------------------------------------------------------

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        include_sensitive: bool = False,
    ) -> tuple[list[MemoryHit], float]:
        if self._vector_store is None or self._embeddings is None:
            return [], 0.0
        start = time.perf_counter()
        emb = await self._embeddings.embed_query(query)
        results = await self._vector_store.similarity_search(
            query_embedding=emb,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        hits = [
            MemoryHit(
                id=r.metadata.get("memory_id", r.chunk_id),
                text=r.text,
                score=r.score,
                section=r.metadata.get("section", DEFAULT_SECTION),
                tags=[t for t in r.metadata.get("tags", "").split(",") if t],
                sensitivity=r.metadata.get("sensitivity", "normal"),
            )
            for r in results
        ]
        # Default-deny: drop sensitive memories unless the caller opted in.
        if not include_sensitive:
            hits = [h for h in hits if h.sensitivity == "normal"]
        return hits, (time.perf_counter() - start) * 1000.0
