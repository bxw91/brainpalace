"""The query tool description must not re-enumerate modes (they live in the
mode-field schema enum) so it cannot drift."""

from brainpalace_server.models.query import QueryMode

from brainpalace_cli.mcp_server.server import _TOOL_DESCRIPTIONS

_NON_DEFAULT = [m.value for m in QueryMode if m.value != "hybrid"]


def test_query_description_does_not_enumerate_modes():
    desc = _TOOL_DESCRIPTIONS["query"].lower()
    # naming two or more specific non-default modes == a drifting enumeration
    named = [v for v in _NON_DEFAULT if v in desc]
    assert named == [], f"tool description enumerates modes: {named}"
