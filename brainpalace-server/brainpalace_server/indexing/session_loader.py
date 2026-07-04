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

# seam: single tool-format parser
**Tool seam.** This module (``load_session``) is the *only* Claude-Code-transcript
record-format parser in the extraction path — the one place that reads CC record
shape (``sessionId``, ``message.role``, ``type``, content blocks). To support
another tool's transcripts, add a sibling parser that maps that format into the
same ``(SessionMeta, list[Turn])`` pair; the drain queue, the subagents, and the
graph/memory stores all consume only that pair and are format-agnostic. The
session watcher discovers CC paths (``~/.claude/projects/**/*.jsonl``) but does
no record-shape parsing — a second tool would add only its own discovery there.
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


#: Wrapper tags Claude Code wraps slash-command / local-command turns in; these
#: are machinery, not the human's prompt, so they are skipped when picking a title.
_TITLE_SKIP_PREFIXES = ("<command-", "<local-command", "<bash-", "Caveat:")
#: Max characters for a derived session title (first prompt line).
TITLE_MAX_CHARS = 120


def first_user_prompt_line(
    path: str | Path, max_chars: int = TITLE_MAX_CHARS
) -> str | None:
    """Return the first *line* of the first real user prompt, for a session title.

    Reads the raw transcript and finds the first ``type == "user"`` turn that
    carries human text (a string ``content`` or a ``text`` block), then returns
    that text's first non-empty line, trimmed to ``max_chars``. Tool-result user
    turns and slash-command wrapper turns are skipped. Returns ``None`` when no
    such line exists (unreadable file, no text prompt).

    Unlike :func:`load_session`, this preserves the original first line (it does
    not collapse newlines), so a multi-line prompt yields its leading line as a
    clean title rather than the whole flattened blob.
    """
    p = Path(path)
    try:
        raw_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "user":
            continue
        message = obj.get("message") or {}
        content = message.get("content")
        text: str | None = None
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and str(block.get("text", "")).strip()
                ):
                    text = str(block["text"])
                    break
        if not text:
            continue
        # Take the first human line of the turn, scanning past context wrappers:
        # IDE/system/slash-command injections are not user-typed. They start with
        # "<" (e.g. "<ide_opened_file>…", "<system-reminder>…") or a known
        # prefix, and often precede the real prompt on a later line of the SAME
        # turn — so skip them line-by-line rather than discarding the whole turn.
        title_line = ""
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("<") or s.startswith(_TITLE_SKIP_PREFIXES):
                continue
            title_line = s
            break
        if not title_line:
            continue
        return (
            title_line
            if len(title_line) <= max_chars
            else title_line[: max_chars - 1] + "…"
        )
    return None


def _short(value: Any, limit: int) -> str:
    text = " ".join(str(value).split())
    if limit <= 0:
        return text
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


def load_session(
    path: str | Path, *, text_trunc: int = TEXT_TRUNC
) -> tuple[SessionMeta, list[Turn]]:
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

    # `index` is a positional counter over emitted turns in file order. Incremental
    # resume (session_distill_service) relies on it being STABLE and MONOTONIC: it
    # slices new turns by `index > prior_offset`. That holds only while transcripts
    # are APPEND-ONLY (lines appended, never inserted/reordered) — true for Claude
    # Code JSONL. A tool that rewrote earlier lines would shift indices and mis-slice
    # the resume delta (2b-5). New tool tags must preserve append-only ordering.
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
                    Turn(index, role, "text", _short(block["text"], text_trunc), ts=ts)
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
