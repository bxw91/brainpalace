"""Codex rollout parsing and cross-project ownership."""

from __future__ import annotations

from pathlib import Path

import brainpalace_server.sessions.adapters.codex  # noqa: F401  (registers)
from brainpalace_server.sessions.adapters import get_adapter

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sessions" / "codex_rollout.jsonl"


def test_parse_reads_meta_from_session_meta_line():
    meta, _turns = get_adapter("codex").parse(FIXTURE)

    assert meta.session_id == "019f823d-c5b7-71f2-8a16-cf0d892107ad"
    assert meta.project_path == "/proj/ours"
    assert meta.started_at == "2026-07-21T01:15:14.282Z"
    assert meta.tool == "codex"


def test_parse_emits_turns_in_file_order():
    _meta, turns = get_adapter("codex").parse(FIXTURE)

    kinds = [(t.role, t.kind) for t in turns]
    assert ("user", "text") in kinds
    assert ("assistant", "tool_use") in kinds
    assert ("assistant", "tool_result") in kinds
    assert ("assistant", "text") in kinds
    assert [t.index for t in turns] == list(range(len(turns)))


def test_event_msg_records_are_ignored_to_avoid_double_counting():
    """`agent_message`/`user_message` mirror `response_item.message` 1:1.

    A real rollout has exactly as many `agent_message` events as
    `response_item.message role=assistant` records — reading both would count
    every assistant and user turn twice.
    """
    _meta, turns = get_adapter("codex").parse(FIXTURE)

    texts = [t.text for t in turns if t.kind == "text"]
    assert texts.count("Added a bounded retry to uploader.py.") == 1
    assert texts.count("add a retry to the uploader") == 1


def test_developer_role_messages_are_skipped():
    """`role=developer` carries injected system prompts, not conversation."""
    _meta, turns = get_adapter("codex").parse(FIXTURE)

    assert all("permissions instructions" not in t.text for t in turns)
    assert all(t.role != "developer" for t in turns)


def test_encrypted_reasoning_yields_no_thinking_turn():
    """Codex reasoning summaries are empty; content is an encrypted blob."""
    _meta, turns = get_adapter("codex").parse(FIXTURE)

    assert not [t for t in turns if t.kind == "thinking"]
    assert all("gAAAAAB" not in t.text for t in turns)


def test_token_count_events_are_skipped():
    _meta, turns = get_adapter("codex").parse(FIXTURE)
    assert all("812" not in t.text for t in turns)


def test_tool_call_name_and_inputs_are_captured():
    _meta, turns = get_adapter("codex").parse(FIXTURE)
    calls = [t for t in turns if t.kind == "tool_use"]
    assert calls[0].tool_name == "shell"
    assert calls[0].tool_inputs["command"] == "ls src"


def test_custom_tool_call_input_is_a_raw_string_not_json():
    _meta, turns = get_adapter("codex").parse(FIXTURE)
    exec_calls = [t for t in turns if t.tool_name == "exec"]
    assert exec_calls[0].tool_inputs["input"] == "const x = 1;"


def test_tool_output_block_lists_are_flattened():
    _meta, turns = get_adapter("codex").parse(FIXTURE)
    results = [t for t in turns if t.kind == "tool_result"]
    assert "uploader.py" in results[0].text


def test_owns_matches_only_the_declared_cwd():
    adapter = get_adapter("codex")
    assert adapter.owns(FIXTURE, "/proj/ours") is True
    assert adapter.owns(FIXTURE, "/proj/theirs") is False


def test_owns_is_false_for_unreadable_file(tmp_path):
    assert get_adapter("codex").owns(tmp_path / "nope.jsonl", "/proj/ours") is False


def test_owns_is_memoised_per_file_stat(tmp_path, monkeypatch):
    """The global store is re-swept on a timer; don't re-read unchanged files."""
    import shutil

    from brainpalace_server.sessions.adapters import codex as codex_mod

    target = tmp_path / "rollout-x.jsonl"
    shutil.copy(FIXTURE, target)
    adapter = get_adapter("codex")
    adapter.clear_ownership_cache()

    calls = {"n": 0}
    real = codex_mod._session_meta_payload

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(codex_mod, "_session_meta_payload", counting)

    assert adapter.owns(target, "/proj/ours") is True
    assert adapter.owns(target, "/proj/ours") is True
    assert calls["n"] == 1  # second call served from the cache


def test_ownership_cache_is_invalidated_when_the_file_changes(tmp_path):
    import json
    import os
    import shutil

    target = tmp_path / "rollout-y.jsonl"
    shutil.copy(FIXTURE, target)
    adapter = get_adapter("codex")
    adapter.clear_ownership_cache()

    assert adapter.owns(target, "/proj/ours") is True

    target.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-21T02:00:00Z",
                "type": "session_meta",
                "payload": {"session_id": "s2", "cwd": "/proj/theirs"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(target, (1e9, 1e9))  # force a distinct mtime

    assert adapter.owns(target, "/proj/ours") is False


def test_discover_walks_the_date_partitioned_tree(tmp_path):
    import shutil

    day = tmp_path / "2026" / "07" / "21"
    day.mkdir(parents=True)
    shutil.copy(FIXTURE, day / "rollout-2026-07-21T01-15-14-abc.jsonl")

    found = get_adapter("codex").discover(tmp_path, "/proj/ours")

    assert [p.name for p in found] == ["rollout-2026-07-21T01-15-14-abc.jsonl"]


def test_source_dirs_is_the_global_store(tmp_path):
    assert get_adapter("codex").source_dirs("/proj", home=tmp_path) == [
        tmp_path / ".codex" / "sessions"
    ]


def test_codex_has_no_subagent_concept():
    adapter = get_adapter("codex")
    assert adapter.is_subagent(FIXTURE) is False
    assert adapter.parent_session_id(FIXTURE) is None


def test_title_is_the_first_user_message(tmp_path):
    assert get_adapter("codex").title(FIXTURE) == "add a retry to the uploader"
