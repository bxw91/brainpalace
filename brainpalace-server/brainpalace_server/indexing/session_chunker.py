"""Phase 050 — sliding-window chunker for session transcripts.

Groups :class:`Turn`s (from :mod:`session_loader`) into overlapping windows and
emits :class:`TextChunk`s tagged ``source_type="session_turn"`` for the existing
vector + BM25 + metadata stack. No LLM here — summaries/decisions/triplets are
phases 060/100.

Design points (roadmap 050 + ADR 0001):

- **Assistant-weighted / privacy-first.** Human ``user`` *text* turns are
  dropped unless ``include_user_turns=True`` (default False). Assistant turns,
  tool calls, and tool results are always kept (tool results aren't human
  dialogue).
- **Content-hash chunk_id** → idempotent dedup: re-ingesting an unchanged
  window yields the same id, so an upsert re-embeds nothing.
- **Reference, not copy.** Chunks carry ``session_id`` + source path + the
  window's starting turn index; the raw JSONL stays the L3 verbatim tier.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

from brainpalace_server.indexing.chunking import ChunkMetadata, TextChunk

if TYPE_CHECKING:
    from brainpalace_server.indexing.session_loader import SessionMeta, Turn

_FENCE_RE = re.compile(r"```([A-Za-z0-9_+-]*)")

DEFAULT_WINDOW = 4
DEFAULT_STRIDE = 2

_ENC: Any = None
try:  # token counting mirrors the rest of the indexer; degrade gracefully
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 — offline / missing model files
    _ENC = None


def _count_tokens(text: str) -> int:
    if _ENC is not None:
        try:
            return len(_ENC.encode(text, disallowed_special=()))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


class SessionChunker:
    """Turn a session's :class:`Turn` list into ``session_turn`` chunks."""

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        stride: int = DEFAULT_STRIDE,
        include_user_turns: bool = False,
    ) -> None:
        self.window = max(1, window)
        self.stride = max(1, stride)
        self.include_user_turns = include_user_turns

    # -- turn rendering ----------------------------------------------------

    def _keep(self, turn: Turn) -> bool:
        """Drop human user *dialogue* unless opted in; keep everything else."""
        if turn.role == "user" and turn.kind == "text" and not self.include_user_turns:
            return False
        return True

    @staticmethod
    def _render(turn: Turn) -> str:
        if turn.kind == "tool_use":
            args = "; ".join(f"{k}={v}" for k, v in turn.tool_inputs.items())
            return f"{turn.role}: {turn.tool_name}({args})"
        if turn.kind == "tool_result":
            return f"tool_result: {turn.text}"
        if turn.kind == "thinking":
            return f"{turn.role} (thinking): {turn.text}"
        return f"{turn.role}: {turn.text}"

    # -- public API --------------------------------------------------------

    def chunk(self, meta: SessionMeta, turns: list[Turn]) -> list[TextChunk]:
        kept = [t for t in turns if self._keep(t)]
        if not kept:
            return []

        windows: list[list[Turn]] = []
        n = len(kept)
        start = 0
        while start < n:
            group = kept[start : start + self.window]
            # Emit full windows; emit a short window only when it's the first
            # (so tiny sessions still produce one chunk) — otherwise it's
            # already covered by the previous full window.
            if start == 0 or start + self.window <= n:
                windows.append(group)
            start += self.stride

        chunks: list[TextChunk] = []
        total = len(windows)
        file_name = meta.session_id or "session"
        for ci, group in enumerate(windows):
            text = "\n".join(self._render(t) for t in group)
            tools_used: list[str] = []
            files_touched: list[str] = []
            roles: list[str] = []
            for t in group:
                if t.role not in roles:
                    roles.append(t.role)
                if t.kind == "tool_use" and t.tool_name:
                    if t.tool_name not in tools_used:
                        tools_used.append(t.tool_name)
                    for key in ("file_path", "path"):
                        val = t.tool_inputs.get(key)
                        if val and val not in files_touched:
                            files_touched.append(val)

            fence = _FENCE_RE.search(text)
            has_code = fence is not None
            language = fence.group(1) if (fence and fence.group(1)) else None

            window_start_index = group[0].index
            digest = hashlib.sha256(
                f"{meta.session_id}\n{text}".encode()
            ).hexdigest()[:32]
            chunk_id = f"session:{meta.session_id}:{digest}"

            extra = {
                "session_id": meta.session_id,
                "started_at": meta.started_at,
                "turn_index": window_start_index,
                "turn_span": len(group),
                "role_mix": roles,
                "tools_used": tools_used,
                "files_touched": files_touched,
                "branch": meta.branch,
                "has_code_block": has_code,
                "is_subagent": meta.is_subagent,
                "parent_session_id": meta.parent_session_id,
                "source_path": meta.source_path,
                "content_hash": digest,
            }
            if language:
                extra["language"] = language

            metadata = ChunkMetadata(
                chunk_id=chunk_id,
                source=meta.source_path,
                file_name=file_name,
                chunk_index=ci,
                total_chunks=total,
                source_type="session_turn",
                language=language,
                extra=extra,
            )
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    text=text,
                    source=meta.source_path,
                    chunk_index=ci,
                    total_chunks=total,
                    token_count=_count_tokens(text),
                    metadata=metadata,
                )
            )
        return chunks
