from brainpalace_cli.commands.init import _plan_inputs_from_grid


def test_defaults_from_merged_when_no_edits():
    merged = {
        "session_indexing": {"enabled": False, "archive": {"enabled": True}},
        "session_extraction": {"mode": "off"},
        "git_indexing": {"enabled": False},
    }
    out = _plan_inputs_from_grid(merged, {})
    assert out["sessions"] is False
    assert out["archive"] is True
    assert out["extract"] is False
    assert out["git_history"] is False
    assert out["git_depth"] is None
    assert out["graphrag_extract_mode"] is None


def test_edits_override_and_capture_side_values():
    merged = {"session_extraction": {"mode": "off"}, "git_indexing": {"enabled": False}}
    edits = {
        "session_indexing.enabled": True,
        "session_extraction.mode": "subagent",
        "git_indexing.enabled": True,
        "git_indexing.depth": 100,
        "extraction.mode": "subagent",
    }
    out = _plan_inputs_from_grid(merged, edits)
    assert out["sessions"] is True
    assert out["extract"] is True  # session_extraction.mode != off
    assert out["git_history"] is True
    assert out["git_depth"] == 100
    assert out["graphrag_extract_mode"] == "subagent"
