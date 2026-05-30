"""Phase 050 — tests for the session JSONL loader.

Uses small synthetic fixtures that mirror the Claude Code transcript schema
(real transcripts are never committed — privacy + ADR 0001 "don't copy
transcripts"). The loader must be tolerant of noise lines and malformed JSON.
"""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.indexing.session_loader import (
    SessionMeta,
    Turn,
    is_subagent_path,
    load_session,
    parent_session_id_for,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"
PARENT = FIXTURES / "sess-parent-1.jsonl"
SUBAGENT = FIXTURES / "sess-parent-1" / "subagents" / "agent-aaa.jsonl"


def test_load_session_extracts_meta() -> None:
    meta, turns = load_session(PARENT)
    assert isinstance(meta, SessionMeta)
    assert meta.session_id == "sess-parent-1"
    assert meta.project_path == "/work/proj"
    assert meta.branch == "main"
    assert meta.started_at == "2026-05-20T10:00:01.000Z"
    assert meta.ended_at == "2026-05-20T10:00:12.000Z"
    assert meta.is_subagent is False
    assert meta.parent_session_id is None
    assert str(PARENT) == meta.source_path


def test_load_session_skips_noise_and_malformed() -> None:
    _, turns = load_session(PARENT)
    # queue-operation line + malformed JSON line are dropped; only user/
    # assistant content turns survive.
    assert all(isinstance(t, Turn) for t in turns)
    assert all(t.role in ("user", "assistant") for t in turns)
    kinds = {t.kind for t in turns}
    assert {"text", "thinking", "tool_use", "tool_result"} >= kinds
    assert len(turns) >= 5


def test_turn_indices_are_sequential() -> None:
    _, turns = load_session(PARENT)
    assert [t.index for t in turns] == list(range(len(turns)))


def test_tool_use_captures_name_and_key_inputs() -> None:
    _, turns = load_session(PARENT)
    writes = [t for t in turns if t.kind == "tool_use" and t.tool_name == "Write"]
    assert writes, "expected a Write tool_use turn"
    assert writes[0].tool_inputs.get("file_path") == "app/health.py"
    # Non-key noise should not be retained verbatim beyond key inputs.
    assert "content" in writes[0].tool_inputs  # content IS a key input


def test_subagent_detection_and_parent_linkage() -> None:
    assert is_subagent_path(SUBAGENT) is True
    assert is_subagent_path(PARENT) is False
    assert parent_session_id_for(SUBAGENT) == "sess-parent-1"
    assert parent_session_id_for(PARENT) is None

    meta, turns = load_session(SUBAGENT)
    assert meta.session_id == "sess-sub-aaa"
    assert meta.is_subagent is True
    assert meta.parent_session_id == "sess-parent-1"
    assert len(turns) >= 2


def test_load_missing_file_returns_empty() -> None:
    meta, turns = load_session(FIXTURES / "does-not-exist.jsonl")
    assert turns == []
    assert meta.session_id is None or isinstance(meta.session_id, str)
