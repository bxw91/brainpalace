"""Antigravity CLI adapter.

Store: ``~/.gemini/antigravity-cli/brain/<conversation-uuid>/.system_generated/
logs/transcript_full.jsonl`` — records
``{step_index, source, type, status, created_at, content, tool_calls, thinking}``.

Two properties drive the design:

1. **The transcript is a REGENERATED projection** of the conversation's SQLite
   DB, not an append log: step statuses mutate in place and indices can be
   missing. ``Turn.index`` therefore carries the record's own ``step_index``
   (stable identity), and steps that are not ``DONE`` are marked
   ``terminal=False`` so the distiller skips them until they settle.
2. **The transcript carries no project.** ``owns()`` joins through
   ``history.jsonl`` (``{conversationId, workspace}``) and matches the workspace
   EXACTLY — a workspace must never claim a project nested underneath it.

The IDE (``~/.gemini/antigravity/conversations/*.pb``) is a different product
with encrypted transcripts and is deliberately not supported.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from brainpalace_server.indexing.session_loader import (
    TEXT_TRUNC,
    THINK_TRUNC,
    TOOL_RESULT_TRUNC,
    SessionMeta,
    Turn,
    _short,
)
from brainpalace_server.sessions.adapters import register_adapter

#: The unabridged rendering. ``transcript.jsonl`` is the same records with a
#: ``truncated_fields`` projection applied; BrainPalace applies its own
#: truncation, so ingesting that one would truncate twice.
TRANSCRIPT_NAME = "transcript_full.jsonl"

#: Step statuses that will never change again. ERROR is FINAL — treating it as
#: in-flight would strand the step forever, because it never becomes DONE.
_TERMINAL_STATUSES = {"DONE", "ERROR"}

#: Antigravity splits a tool invocation across TWO records: a PLANNER_RESPONSE
#: carrying the prose + `tool_calls`, then an outcome record of one of these
#: types whose `content` is the tool OUTPUT. Classifying these as prose would
#: index raw command output as assistant text and apply the wrong truncation
#: (TEXT_TRUNC 1500 instead of TOOL_RESULT_TRUNC 240).
_TOOL_RESULT_TYPES = {
    "RUN_COMMAND",
    "VIEW_FILE",
    "GREP_SEARCH",
    "LIST_DIRECTORY",
    "SEARCH_WEB",
    "CODE_ACTION",
}

#: Antigravity's file-path argument names, mapped to the canonical `file_path`
#: key that ``session_loader.FILE_INPUT_KEYS`` (and therefore the chunker's
#: ``files_touched``) recognises. Normalising here keeps the chunker untouched.
_PATH_ARG_KEYS = ("AbsolutePath", "TargetFile", "SearchPath", "DirectoryPath")

#: Antigravity wraps the human prompt in this tag.
_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)


def _records(path: Path) -> list[dict[str, Any]]:
    """Parsed records in file order; malformed lines skipped."""
    out: list[dict[str, Any]] = []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "step_index" in obj:
            out.append(obj)
    return out


def _conversation_id(path: Path) -> str | None:
    """``…/brain/<conversation-id>/.system_generated/logs/<file>``."""
    parts = Path(path).parts
    if "brain" not in parts:
        return None
    idx = parts.index("brain")
    return parts[idx + 1] if idx + 1 < len(parts) else None


def _cli_root(path: Path) -> Path | None:
    """The ``antigravity-cli`` root above a transcript path."""
    parts = Path(path).parts
    if "brain" not in parts:
        return None
    return Path(*parts[: parts.index("brain")])


def _workspace_for(root: Path, conversation_id: str) -> str | None:
    """Workspace path for a conversation, from ``history.jsonl``."""
    history = root / "history.jsonl"
    try:
        raw_lines = history.read_text(encoding="utf-8", errors="replace").splitlines()
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
        if isinstance(obj, dict) and obj.get("conversationId") == conversation_id:
            ws = obj.get("workspace")
            return str(ws) if ws else None
    return None


def _user_text(content: str) -> str:
    """Unwrap ``<USER_REQUEST>…</USER_REQUEST>``, dropping metadata blocks."""
    match = _USER_REQUEST_RE.search(content)
    return (match.group(1) if match else content).strip()


class AntigravityAdapter:
    """Antigravity CLI conversation transcripts."""

    slug = "antigravity"

    def source_dirs(self, project_root: str, home: Path) -> list[Path]:
        return [home / ".gemini" / "antigravity-cli"]

    def discover(self, src: Path, project_root: str) -> list[Path]:
        if not src.exists():
            return []
        return sorted(src.glob(f"brain/*/.system_generated/logs/{TRANSCRIPT_NAME}"))

    def owns(self, path: Path, project_root: str) -> bool:
        path = Path(path)
        conversation_id = _conversation_id(path)
        root = _cli_root(path)
        if conversation_id is None or root is None:
            return False
        workspace = _workspace_for(root, conversation_id)
        # Exact match only: a workspace of /home/u must not claim /home/u/proj.
        return workspace == project_root

    def parse(
        self, path: Path, *, text_trunc: int = TEXT_TRUNC
    ) -> tuple[SessionMeta, list[Turn]]:
        path = Path(path)
        records = _records(path)
        meta = SessionMeta(
            session_id=_conversation_id(path) or path.stem,
            project_path=None,
            branch=None,
            started_at=records[0].get("created_at") if records else None,
            ended_at=records[-1].get("created_at") if records else None,
            source_path=str(path),
            tool=self.slug,
        )
        root = _cli_root(path)
        if root is not None and meta.session_id:
            meta.project_path = _workspace_for(root, meta.session_id)

        turns: list[Turn] = []
        for rec in records:
            index = int(rec.get("step_index", 0))
            terminal = str(rec.get("status") or "") in _TERMINAL_STATUSES
            rtype = str(rec.get("type") or "")
            source = str(rec.get("source") or "")
            role = "user" if source.startswith("USER") else "assistant"
            ts = rec.get("created_at")
            content = str(rec.get("content") or "")

            thinking = str(rec.get("thinking") or "").strip()
            if thinking:
                turns.append(
                    Turn(
                        index,
                        role,
                        "thinking",
                        _short(thinking, THINK_TRUNC),
                        ts=ts,
                        terminal=terminal,
                    )
                )

            # Content FIRST, then any tool call. A record commonly carries both
            # — real transcripts attach `tool_calls` to a PLANNER_RESPONSE whose
            # `content` is the assistant explaining what it is about to do — so
            # these are additive, never either/or. Both share the step's index.
            if rtype in _TOOL_RESULT_TYPES:
                # Outcome record: `content` is tool OUTPUT, not prose.
                if content.strip():
                    turns.append(
                        Turn(
                            index,
                            role,
                            "tool_result",
                            _short(content, TOOL_RESULT_TRUNC),
                            ts=ts,
                            terminal=terminal,
                        )
                    )
            else:
                text = _user_text(content) if role == "user" else content.strip()
                if text:
                    turns.append(
                        Turn(
                            index,
                            role,
                            "text",
                            _short(text, text_trunc),
                            ts=ts,
                            terminal=terminal,
                        )
                    )

            calls = rec.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    # The args key is `args` — NOT `arguments`.
                    args = call.get("args")
                    inputs = (
                        {k: _short(v, 200) for k, v in args.items() if v}
                        if isinstance(args, dict)
                        else {}
                    )
                    # Normalise Antigravity's path arg names onto `file_path`,
                    # which is what FILE_INPUT_KEYS (and the chunker's
                    # files_touched) looks for. Without this every Antigravity
                    # session reports zero files touched.
                    for key in _PATH_ARG_KEYS:
                        if inputs.get(key):
                            inputs.setdefault("file_path", inputs[key])
                            break
                    turns.append(
                        Turn(
                            index,
                            role,
                            "tool_use",
                            "",
                            tool_name=str(call.get("name") or rtype.lower()),
                            tool_inputs=inputs,
                            ts=ts,
                            terminal=terminal,
                        )
                    )

        turns.sort(key=lambda t: t.index)
        return meta, turns

    def title(self, path: Path, max_chars: int = 120) -> str | None:
        for rec in _records(Path(path)):
            if str(rec.get("type") or "") != "USER_INPUT":
                continue
            text = _user_text(str(rec.get("content") or ""))
            for line in text.splitlines():
                line = line.strip()
                if line:
                    return (
                        line if len(line) <= max_chars else line[: max_chars - 1] + "…"
                    )
        return None

    def is_subagent(self, path: Path) -> bool:
        return False

    def parent_session_id(self, path: Path) -> str | None:
        return None


register_adapter(AntigravityAdapter())
