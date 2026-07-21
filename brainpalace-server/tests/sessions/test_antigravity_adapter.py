"""Antigravity CLI transcript parsing, ownership join, and rewrite safety."""

from __future__ import annotations

import shutil
from pathlib import Path

import brainpalace_server.sessions.adapters.antigravity  # noqa: F401  (registers)
from brainpalace_server.sessions.adapters import get_adapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"
TRANSCRIPT = FIXTURES / "antigravity_transcript.jsonl"
HISTORY = FIXTURES / "antigravity_history.jsonl"


def _make_store(tmp_path: Path, conversation_id: str) -> Path:
    """Build a ~/.gemini/antigravity-cli layout under tmp_path."""
    root = tmp_path / ".gemini" / "antigravity-cli"
    logs = root / "brain" / conversation_id / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    shutil.copy(TRANSCRIPT, logs / "transcript_full.jsonl")
    shutil.copy(TRANSCRIPT, logs / "transcript.jsonl")
    shutil.copy(HISTORY, root / "history.jsonl")
    return root


def test_turn_index_comes_from_step_index_not_position():
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    # step_index 2 is absent in the fixture; indices must not be renumbered.
    # Steps 1, 4 and 7 each yield TWO turns sharing one index (thinking+text,
    # text+tool_use) because they are one step and must resume atomically.
    assert [t.index for t in turns] == [0, 1, 1, 3, 4, 4, 5, 6, 7, 7, 8, 9]


def test_co_indexed_turns_belong_to_one_step():
    """Turns from the same record share its step_index, never renumber."""
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    assert {t.kind for t in turns if t.index == 1} == {"thinking", "text"}
    assert {t.kind for t in turns if t.index == 4} == {"text", "tool_use"}


def test_running_steps_are_marked_non_terminal():
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    assert all(t.terminal is False for t in turns if t.index == 3)


def test_error_steps_are_terminal():
    """ERROR is a FINAL state. Treating it as in-flight would strand the step
    forever: it never becomes DONE, so it would never be distilled."""
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    assert all(t.terminal is True for t in turns if t.index == 5)


def test_done_steps_are_terminal():
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    assert all(t.terminal is True for t in turns if t.index == 4)


def test_tool_calls_use_the_args_key_and_ride_on_planner_responses():
    """Real transcripts attach tool_calls to PLANNER_RESPONSE, keyed `args`."""
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    calls = [t for t in turns if t.kind == "tool_use"]
    assert [t.tool_name for t in calls] == ["run_command", "view_file"]
    assert calls[0].tool_inputs["CommandLine"] == "journalctl --list-boots"


def test_prose_on_a_tool_call_record_is_not_dropped():
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    texts = [t.text for t in turns if t.index == 4 and t.kind == "text"]
    assert texts == ["I will list the boot logs next."]


def test_tool_outcome_records_are_tool_results_not_prose():
    """Antigravity splits a call across two records: PLANNER_RESPONSE carries
    the prose + tool_calls, then a RUN_COMMAND record carries the OUTPUT.
    Classifying the output as assistant text would index raw command output as
    prose and truncate it at 1500 instead of 240 chars."""
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    outcome = [t for t in turns if t.index == 8]
    assert [t.kind for t in outcome] == ["tool_result"]
    assert "up 3 days" in outcome[0].text


def test_file_path_args_are_normalised_for_files_touched():
    """Antigravity names paths AbsolutePath/TargetFile/…; the chunker only
    recognises file_path, so without normalisation files_touched is empty."""
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    views = [t for t in turns if t.tool_name == "view_file"]
    assert views[0].tool_inputs["file_path"] == "/proj/ours/uploader.py"
    assert views[0].tool_inputs["AbsolutePath"] == "/proj/ours/uploader.py"


def test_meta_uses_created_at_of_first_and_last_record():
    meta, _turns = get_adapter("antigravity").parse(TRANSCRIPT)
    assert meta.started_at == "2026-06-14T18:49:51Z"
    assert meta.ended_at == "2026-06-14T18:50:30Z"
    assert meta.tool == "antigravity"


def test_session_id_is_the_conversation_dir(tmp_path):
    root = _make_store(tmp_path, "conv-ours")
    t = (
        root
        / "brain"
        / "conv-ours"
        / ".system_generated"
        / "logs"
        / "transcript_full.jsonl"
    )
    meta, _turns = get_adapter("antigravity").parse(t)
    assert meta.session_id == "conv-ours"


def test_roles_and_kinds_are_mapped():
    _meta, turns = get_adapter("antigravity").parse(TRANSCRIPT)
    by_index = {t.index: t for t in turns}
    assert (by_index[0].role, by_index[0].kind) == ("user", "text")
    assert (by_index[1].role, by_index[1].kind) == ("assistant", "text")
    assert by_index[4].kind == "tool_use"
    assert by_index[4].tool_name == "run_command"


def test_discover_finds_only_the_full_transcript(tmp_path):
    root = _make_store(tmp_path, "conv-ours")
    found = get_adapter("antigravity").discover(root, "/proj/ours")
    assert [p.name for p in found] == ["transcript_full.jsonl"]


def test_owns_joins_through_history_jsonl(tmp_path):
    root = _make_store(tmp_path, "conv-ours")
    t = (
        root
        / "brain"
        / "conv-ours"
        / ".system_generated"
        / "logs"
        / "transcript_full.jsonl"
    )
    adapter = get_adapter("antigravity")
    assert adapter.owns(t, "/proj/ours") is True
    assert adapter.owns(t, "/proj/theirs") is False


def test_owns_requires_exact_workspace_match(tmp_path):
    """A workspace must not claim a project nested underneath it."""
    root = _make_store(tmp_path, "conv-ours")
    t = (
        root
        / "brain"
        / "conv-ours"
        / ".system_generated"
        / "logs"
        / "transcript_full.jsonl"
    )
    assert get_adapter("antigravity").owns(t, "/proj/ours/sub") is False


def test_owns_is_false_for_unknown_conversation(tmp_path):
    root = _make_store(tmp_path, "conv-unlisted")
    t = (
        root
        / "brain"
        / "conv-unlisted"
        / ".system_generated"
        / "logs"
        / "transcript_full.jsonl"
    )
    assert get_adapter("antigravity").owns(t, "/proj/ours") is False


def test_source_dirs_points_at_the_cli_root(tmp_path):
    assert get_adapter("antigravity").source_dirs("/proj", home=tmp_path) == [
        tmp_path / ".gemini" / "antigravity-cli"
    ]


def test_title_strips_the_user_request_wrapper():
    assert (
        get_adapter("antigravity").title(TRANSCRIPT) == "explore gnome-shell cpu usage"
    )


def test_no_subagent_concept():
    adapter = get_adapter("antigravity")
    assert adapter.is_subagent(TRANSCRIPT) is False
    assert adapter.parent_session_id(TRANSCRIPT) is None
