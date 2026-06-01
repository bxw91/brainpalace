"""Phase 050 — parse runtime JSONL transcripts into turns + session metadata.

Ported from the throwaway 020-spike ``reduce.py`` (which the spike notes
"doubles as a phase-050 chunker prototype"). Turns a Claude Code session JSONL
into an ordered list of :class:`Turn` records plus a :class:`SessionMeta`.

Per ADR 0001 the raw JSONL on disk is the source-of-truth / L3 verbatim tier —
this loader never copies it; downstream chunks reference ``session_id`` + the
source path + offsets only.

The loader is deliberately tolerant: malformed lines and non-conversational
record types (``queue-operation``, ``attachment``, ``file-history-snapshot``,
…) are skipped rather than raised on, because transcript schemas drift across
runtime versions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Tool-call inputs worth keeping; the rest is noise for recall/extraction.
KEY_INPUTS = (
    "file_path",
    "command",
    "path",
    "pattern",
    "query",
    "description",
    "old_string",
    "url",
    "prompt",
    "content",
)
#: Inputs whose presence implies a file was directly touched (R2: DIRECT only).
FILE_INPUT_KEYS = ("file_path", "path")

TOOL_RESULT_TRUNC = 240
TEXT_TRUNC = 1500
THINK_TRUNC = 300

#: Marker dir that distinguishes a sub-agent (sidechain) transcript on disk:
#: ``<project>/<parent-session-id>/subagents/agent-*.jsonl``.
SUBAGENTS_DIR = "subagents"


@dataclass
class Turn:
    """One conversational unit lifted from the transcript."""

    index: int
    role: str  # "user" | "assistant"
    kind: str  # "text" | "thinking" | "tool_use" | "tool_result"
    text: str
    tool_name: str | None = None
    tool_inputs: dict[str, Any] = field(default_factory=dict)
    ts: str | None = None


@dataclass
class SessionMeta:
    """Provenance for a single session transcript."""

    session_id: str | None
    project_path: str | None
    branch: str | None
    started_at: str | None
    ended_at: str | None
    source_path: str
    is_subagent: bool = False
    parent_session_id: str | None = None
    origin_path: str | None = None


def is_subagent_path(path: str | Path) -> bool:
    """True when the transcript lives under a ``subagents/`` directory."""
    return SUBAGENTS_DIR in Path(path).parts


def parent_session_id_for(path: str | Path) -> str | None:
    """Return the parent session id for a sub-agent transcript, else None.

    Layout: ``.../<parent-session-id>/subagents/agent-*.jsonl`` — the parent id
    is the directory that *contains* the ``subagents/`` dir.
    """
    parts = Path(path).parts
    if SUBAGENTS_DIR not in parts:
        return None
    idx = parts.index(SUBAGENTS_DIR)
    if idx == 0:
        return None
    return parts[idx - 1]


def _short(value: Any, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + " …"


def _blocks(message: dict[str, Any]) -> list[Any]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _tool_inputs(block: dict[str, Any]) -> dict[str, Any]:
    raw = block.get("input") or {}
    kept: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key in KEY_INPUTS:
            if key in raw and raw[key]:
                kept[key] = _short(raw[key], 200) if key != "file_path" else raw[key]
    return kept


def _tool_result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
    return _short(content or "", TOOL_RESULT_TRUNC)


def load_session(path: str | Path) -> tuple[SessionMeta, list[Turn]]:
    """Parse a session JSONL into (metadata, ordered turns).

    Missing/unreadable files yield an empty turn list with best-effort meta.
    """
    p = Path(path)
    meta = SessionMeta(
        session_id=None,
        project_path=None,
        branch=None,
        started_at=None,
        ended_at=None,
        source_path=str(p),
        is_subagent=is_subagent_path(p),
        parent_session_id=parent_session_id_for(p),
    )
    turns: list[Turn] = []
    try:
        raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return meta, turns

    index = 0
    seen_meta = False
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue

        if not seen_meta:
            meta.session_id = obj.get("sessionId") or meta.session_id
            meta.project_path = obj.get("cwd")
            meta.branch = obj.get("gitBranch")
            meta.started_at = obj.get("timestamp")
            seen_meta = True
        # session_id may only appear on later lines for some record orders.
        if meta.session_id is None and obj.get("sessionId"):
            meta.session_id = obj.get("sessionId")
        if obj.get("timestamp"):
            meta.ended_at = obj.get("timestamp")

        message = obj.get("message") or {}
        role = str(message.get("role") or obj.get("type") or "")
        ts = obj.get("timestamp")

        for block in _blocks(message):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                turns.append(
                    Turn(index, role, "text", _short(block["text"], TEXT_TRUNC), ts=ts)
                )
                index += 1
            elif btype == "thinking" and block.get("thinking", "").strip():
                turns.append(
                    Turn(
                        index,
                        role,
                        "thinking",
                        _short(block["thinking"], THINK_TRUNC),
                        ts=ts,
                    )
                )
                index += 1
            elif btype == "tool_use":
                turns.append(
                    Turn(
                        index,
                        role,
                        "tool_use",
                        "",
                        tool_name=block.get("name", "?"),
                        tool_inputs=_tool_inputs(block),
                        ts=ts,
                    )
                )
                index += 1
            elif btype == "tool_result":
                turns.append(
                    Turn(index, role, "tool_result", _tool_result_text(block), ts=ts)
                )
                index += 1

    return meta, turns
