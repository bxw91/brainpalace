"""Every transcript read dispatches to the owning tool's parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainpalace_server.sessions.parse import (
    parse_transcript,
    tool_for_archived_path,
)


def _cc(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "sess-1",
                "cwd": "/proj",
                "timestamp": "2026-07-21T10:00:00Z",
                "message": {"role": "user", "content": "hello"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _codex(path: Path) -> None:
    lines = [
        {
            "timestamp": "2026-07-21T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "session_id": "cdx-1",
                "cwd": "/proj",
                "timestamp": "2026-07-21T10:00:00Z",
            },
        },
        {
            "timestamp": "2026-07-21T10:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello from codex"}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "folder,expected",
    [
        ("2026-07-21-claude-code", "claude-code"),
        ("2026-07-21-codex", "codex"),
        ("2026-07-21-antigravity", "antigravity"),
        ("undated-codex", "codex"),
        ("not-an-archive-folder", None),
    ],
)
def test_tool_inferred_from_archive_folder(tmp_path, folder, expected):
    d = tmp_path / folder
    d.mkdir()
    f = d / "s.jsonl"
    f.write_text("", encoding="utf-8")
    assert tool_for_archived_path(f) == expected


def test_tool_inferred_through_a_subagent_subtree(tmp_path):
    d = tmp_path / "2026-07-21-claude-code" / "parent-1" / "subagents"
    d.mkdir(parents=True)
    f = d / "agent-x.jsonl"
    f.write_text("", encoding="utf-8")
    assert tool_for_archived_path(f) == "claude-code"


def test_explicit_tool_wins_over_inference(tmp_path):
    d = tmp_path / "2026-07-21-codex"
    d.mkdir()
    f = d / "s.jsonl"
    _cc(f)
    meta, turns = parse_transcript(f, tool="claude-code")
    assert meta.session_id == "sess-1"
    assert [t.text for t in turns] == ["hello"]


# NOTE: the codex-specific dispatch tests (a codex file under a codex folder
# parsing via inference, and title dispatch) are appended by Task 8 — the
# CodexAdapter is not registered until then, so asserting codex parsing here
# would fail on the claude-code fallback. The `_codex` helper above is used by
# Task 8's additions to THIS file.


def test_unknown_folder_falls_back_to_claude_code(tmp_path):
    f = tmp_path / "s.jsonl"
    _cc(f)
    meta, turns = parse_transcript(f)
    assert meta.tool == "claude-code"
    assert len(turns) == 1


def test_unregistered_tool_falls_back_rather_than_raising(tmp_path):
    d = tmp_path / "2026-07-21-no-such-tool"
    d.mkdir()
    f = d / "s.jsonl"
    _cc(f)
    meta, _turns = parse_transcript(f)
    assert meta.tool == "claude-code"


def test_title_dispatches_to_claude_code_by_default(tmp_path):
    """Titles go through the adapter dispatcher, not first_user_prompt_line."""
    from brainpalace_server.sessions.parse import title_for_transcript

    d = tmp_path / "2026-07-21-claude-code"
    d.mkdir()
    f = d / "s.jsonl"
    _cc(f)

    assert title_for_transcript(f) == "hello"


def test_codex_transcript_parses_via_inference(tmp_path):
    """The regression the dispatcher exists for: a codex file under a codex
    folder must parse with the codex adapter, not fall back to claude-code."""
    d = tmp_path / "2026-07-21-codex"
    d.mkdir()
    f = d / "cdx-1.jsonl"
    _codex(f)

    meta, turns = parse_transcript(f)

    assert meta.tool == "codex"
    assert meta.session_id == "cdx-1"
    assert meta.started_at == "2026-07-21T10:00:00Z"
    assert [t.text for t in turns] == ["hello from codex"]


def test_title_dispatches_by_archive_folder(tmp_path):
    """The dashboard archive list derives titles; a codex file must not be fed
    to the Claude-Code title extractor (which would return None)."""
    from brainpalace_server.sessions.parse import title_for_transcript

    d = tmp_path / "2026-07-21-codex"
    d.mkdir()
    f = d / "cdx-1.jsonl"
    _codex(f)

    assert title_for_transcript(f) == "hello from codex"
