"""The hook subagent guard covers all 9 query modes and its deny-reason is built
from the same tuple."""

from brainpalace_server.models.query import QueryMode

from brainpalace_cli.commands import hook


def test_guard_tuple_covers_all_modes():
    assert set(hook._GUARD_QUERY_MODES) == {m.value for m in QueryMode}


def test_deny_reason_lists_every_mode():
    for m in QueryMode:
        assert m.value in hook._GUARD_DENY_REASON


def test_new_modes_match_via_cli_regex():
    # A subagent prompt using a new mode now satisfies the guard (CLI form).
    prompt = "Find callers: `brainpalace query 'x' --mode timeline`"
    assert hook._GUARD_DIRECTIVE_CLI_RE.search(prompt) is not None


def test_new_modes_match_via_mcp_regex():
    # ...and the MCP form (mode arg near a brainpalace mention).
    prompt = "Explore with the brainpalace query tool, mode: timeline"
    assert hook._GUARD_DIRECTIVE_MCP_RE.search(prompt) is not None
