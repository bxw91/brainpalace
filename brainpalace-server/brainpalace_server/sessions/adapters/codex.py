"""Codex adapter — ``~/.codex/sessions/YYYY/MM/DD/rollout-<ISO>-<uuid>.jsonl``.

Records are ``{"timestamp", "type", "payload"}`` where ``type`` is one of
``session_meta``, ``response_item``, ``event_msg``, ``turn_context``,
``world_state``.

The store is GLOBAL — every project's rollouts share one tree — so ``owns()``
is load-bearing: it reads the first ``session_meta`` line and compares
``payload.cwd`` to the project root. Only that first line is read, so the check
stays cheap over a large store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
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

#: Rollout files are named ``rollout-<ISO>-<uuid>.jsonl``.
_ROLLOUT_GLOB = "**/rollout-*.jsonl"

#: How many leading lines ``_session_meta_payload`` scans before giving up.
#: The meta record is the first line in practice; the bound keeps a malformed
#: file from being slurped whole just to answer "is this ours".
_META_SCAN_LINES = 20


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects, skipping blank and malformed lines."""
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _session_meta_payload(path: Path) -> dict[str, Any] | None:
    """First ``session_meta`` payload, or None.

    STREAMS and stops at the first match — ``owns()`` calls this across the
    whole global store every sweep, and rollouts can be megabytes; reading the
    entire file here would make ownership checks O(store size).
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(_META_SCAN_LINES):
                raw = fh.readline()
                if not raw:
                    return None
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("type") == "session_meta":
                    payload = obj.get("payload")
                    return payload if isinstance(payload, dict) else None
    except OSError:
        return None
    return None


def _text_of(content: Any) -> str:
    """Flatten a Codex content list into plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return " ".join(parts)


class CodexAdapter:
    """Codex rollout transcripts."""

    slug = "codex"

    def __init__(self) -> None:
        # (path, mtime, size) -> recorded cwd. The store is global and swept on
        # a timer, so without this every sweep re-opens every rollout in the
        # tree just to answer "is this ours". Stat-gated, matching how
        # SessionArchiveService.sync already dedups unchanged files.
        self._cwd_cache: dict[str, tuple[float, int, str]] = {}

    def clear_ownership_cache(self) -> None:
        """Drop memoised ownership answers (tests, and after a rehome)."""
        self._cwd_cache.clear()

    def source_dirs(self, project_root: str, home: Path) -> list[Path]:
        return [home / ".codex" / "sessions"]

    def discover(self, src: Path, project_root: str) -> list[Path]:
        if not src.exists():
            return []
        return sorted(src.glob(_ROLLOUT_GLOB))

    def _cwd_of(self, path: Path) -> str | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        cached = self._cwd_cache.get(str(path))
        if (
            cached is not None
            and cached[0] == stat.st_mtime
            and cached[1] == stat.st_size
        ):
            return cached[2]
        payload = _session_meta_payload(path)
        if payload is None:
            return None
        cwd = str(payload.get("cwd") or "")
        self._cwd_cache[str(path)] = (stat.st_mtime, stat.st_size, cwd)
        return cwd

    def owns(self, path: Path, project_root: str) -> bool:
        return self._cwd_of(Path(path)) == project_root

    def parse(
        self, path: Path, *, text_trunc: int = TEXT_TRUNC
    ) -> tuple[SessionMeta, list[Turn]]:
        path = Path(path)
        meta = SessionMeta(
            session_id=None,
            project_path=None,
            branch=None,
            started_at=None,
            ended_at=None,
            source_path=str(path),
            tool=self.slug,
        )
        turns: list[Turn] = []
        index = 0

        for obj in _iter_records(path):
            rtype = obj.get("type")
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            ts = obj.get("timestamp")
            if ts:
                meta.ended_at = ts

            if rtype == "session_meta":
                meta.session_id = payload.get("session_id") or meta.session_id
                meta.project_path = payload.get("cwd") or meta.project_path
                meta.started_at = meta.started_at or payload.get("timestamp") or ts
                continue

            # `event_msg` records MIRROR `response_item` content, so reading
            # both double-counts every turn. Measured across 7 real rollouts:
            #   assistant: agent_message 58 == response_item role=assistant 58
            #              (exact match in EVERY file, not just in aggregate)
            #   user:      user_message  29 <  response_item role=user      36
            #              (response_item is a strict SUPERSET — exactly one
            #               extra per session, the injected context turn)
            # So `response_item` alone loses nothing, and every `event_msg`
            # (token_count, task_started, web_search_end, …) is skipped.
            if rtype != "response_item":
                continue

            ptype = payload.get("type")

            if ptype == "message":
                role = str(payload.get("role") or "assistant")
                # `developer` messages are injected system prompts (permissions
                # blocks, tool instructions) — machinery, not conversation.
                if role == "developer":
                    continue
                text = _text_of(payload.get("content")).strip()
                if text:
                    turns.append(
                        Turn(index, role, "text", _short(text, text_trunc), ts=ts)
                    )
                    index += 1
            elif ptype == "reasoning":
                # Defensive only: in practice `summary` is always empty and the
                # real reasoning lives in `encrypted_content`, which we never
                # touch. Emit a thinking turn only if a plaintext summary exists.
                text = _text_of(payload.get("summary")).strip()
                if text:
                    turns.append(
                        Turn(
                            index,
                            "assistant",
                            "thinking",
                            _short(text, THINK_TRUNC),
                            ts=ts,
                        )
                    )
                    index += 1
            elif ptype in ("function_call", "custom_tool_call"):
                turns.append(
                    Turn(
                        index,
                        "assistant",
                        "tool_use",
                        "",
                        tool_name=str(payload.get("name") or "?"),
                        tool_inputs=self._tool_inputs(payload),
                        ts=ts,
                    )
                )
                index += 1
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                out = payload.get("output")
                text = out if isinstance(out, str) else _text_of(out)
                turns.append(
                    Turn(
                        index,
                        "assistant",
                        "tool_result",
                        _short(text, TOOL_RESULT_TRUNC),
                        ts=ts,
                    )
                )
                index += 1

        if meta.session_id is None:
            meta.session_id = path.stem
        return meta, turns

    @staticmethod
    def _tool_inputs(payload: dict[str, Any]) -> dict[str, Any]:
        """Tool arguments.

        ``function_call`` serialises them as a JSON *string* in ``arguments``.
        ``custom_tool_call`` puts a raw payload (often a code snippet) in
        ``input``, which is NOT JSON — keep it under an ``input`` key rather
        than pretending to parse it.
        """
        raw = payload.get("arguments")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"arguments": _short(raw, 200)}
            if isinstance(parsed, dict):
                return {k: _short(v, 200) for k, v in parsed.items() if v}
            return {"arguments": _short(raw, 200)}

        raw_input = payload.get("input")
        if isinstance(raw_input, str) and raw_input:
            return {"input": _short(raw_input, 200)}
        if isinstance(raw_input, dict):
            return {k: _short(v, 200) for k, v in raw_input.items() if v}
        return {}

    def title(self, path: Path, max_chars: int = 120) -> str | None:
        for obj in _iter_records(Path(path)):
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            if obj.get("type") != "response_item":
                continue
            if payload.get("type") != "message" or payload.get("role") != "user":
                continue
            text = _text_of(payload.get("content")).strip()
            # Codex sessions carry exactly one injected-context user turn per
            # session (a response_item with no matching user_message event);
            # its lines are tag-wrapped. Skip "<"-prefixed lines the same way
            # first_user_prompt_line does, so the title is the human's prompt,
            # not "<environment_context>…".
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("<"):
                    continue
                return line if len(line) <= max_chars else line[: max_chars - 1] + "…"
        return None

    def is_subagent(self, path: Path) -> bool:
        return False

    def parent_session_id(self, path: Path) -> str | None:
        return None


register_adapter(CodexAdapter())
