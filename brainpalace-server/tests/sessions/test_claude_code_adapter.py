"""Claude Code adapter must reproduce pre-refactor loader behaviour exactly."""

from __future__ import annotations

import json
from pathlib import Path

import brainpalace_server.sessions.adapters.claude_code  # noqa: F401  (registers)
from brainpalace_server.indexing.session_loader import load_session
from brainpalace_server.sessions.adapters import get_adapter


def _write_cc_transcript(path: Path) -> None:
    lines = [
        {
            "type": "user",
            "sessionId": "sess-1",
            "cwd": "/proj",
            "gitBranch": "main",
            "timestamp": "2026-07-21T10:00:00Z",
            "message": {"role": "user", "content": "make the thing"},
        },
        {
            "type": "assistant",
            "sessionId": "sess-1",
            "timestamp": "2026-07-21T10:00:05Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def test_parse_matches_load_session(tmp_path):
    p = tmp_path / "sess-1.jsonl"
    _write_cc_transcript(p)
    adapter = get_adapter("claude-code")

    a_meta, a_turns = adapter.parse(p)
    l_meta, l_turns = load_session(p)

    assert a_meta.session_id == l_meta.session_id == "sess-1"
    assert a_meta.project_path == "/proj"
    assert a_meta.branch == "main"
    assert [t.text for t in a_turns] == [t.text for t in l_turns]


def test_tool_slug_is_stamped_on_meta(tmp_path):
    p = tmp_path / "sess-1.jsonl"
    _write_cc_transcript(p)
    meta, _turns = get_adapter("claude-code").parse(p)
    assert meta.tool == "claude-code"


def test_source_dirs_encodes_project_path(tmp_path):
    adapter = get_adapter("claude-code")
    dirs = adapter.source_dirs("/home/u/proj", home=tmp_path)
    assert dirs == [tmp_path / ".claude" / "projects" / "-home-u-proj"]


def test_owns_is_true_because_directory_is_the_project(tmp_path):
    adapter = get_adapter("claude-code")
    assert adapter.owns(tmp_path / "sess-1.jsonl", "/home/u/proj") is True


def test_discover_finds_top_level_and_subagents(tmp_path):
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    sub = tmp_path / "parent-1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.jsonl").write_text("", encoding="utf-8")
    found = get_adapter("claude-code").discover(tmp_path, "/proj")
    assert [p.name for p in found] == ["a.jsonl", "agent-x.jsonl"]


def test_subagent_helpers(tmp_path):
    adapter = get_adapter("claude-code")
    sub = tmp_path / "parent-1" / "subagents" / "agent-x.jsonl"
    assert adapter.is_subagent(sub) is True
    assert adapter.parent_session_id(sub) == "parent-1"
    assert adapter.is_subagent(tmp_path / "a.jsonl") is False
