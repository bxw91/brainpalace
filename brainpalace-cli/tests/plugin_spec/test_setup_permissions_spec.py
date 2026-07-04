"""Regression checks for setup-assistant policy island wiring."""

import json
from pathlib import Path

import pytest

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


PLUGIN_DIR = Path(__file__).resolve().parents[3] / "brainpalace-plugin"
if not PLUGIN_DIR.is_dir():  # standalone CLI checkout without the plugin tree
    pytest.skip("brainpalace-plugin not present", allow_module_level=True)
AGENT_PATH = PLUGIN_DIR / "agents" / "setup-assistant.md"
COMMAND_PATHS = [
    PLUGIN_DIR / "commands" / "brainpalace-config.md",
    PLUGIN_DIR / "commands" / "brainpalace-install.md",
    PLUGIN_DIR / "commands" / "brainpalace-setup.md",
    PLUGIN_DIR / "commands" / "brainpalace-init.md",
    PLUGIN_DIR / "commands" / "brainpalace-start.md",
    PLUGIN_DIR / "commands" / "brainpalace-verify.md",
]
CONFIG_COMMAND_PATH = PLUGIN_DIR / "commands" / "brainpalace-config.md"
INSTALL_COMMAND_PATH = PLUGIN_DIR / "commands" / "brainpalace-install.md"
PYPI_VERSION_SCRIPT_PATH = PLUGIN_DIR / "scripts" / "bp-pypi-version.sh"
UV_CHECK_SCRIPT_PATH = PLUGIN_DIR / "scripts" / "bp-uv-check.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(relative_path: str) -> dict:
    """Parse YAML frontmatter from a plugin .md file.

    Returns the parsed dict.  ``tools`` is normalised: always a set of strings
    (splits comma-separated strings; handles list or None/empty list).
    """
    if _yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required for frontmatter tests")
    path = PLUGIN_DIR / relative_path
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next(
        (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if end is None:
        return {}
    fm = _yaml.safe_load("\n".join(lines[1:end])) or {}
    raw_tools = fm.get("tools")
    if not raw_tools:
        fm["tools"] = set()
    elif isinstance(raw_tools, str):
        fm["tools"] = {t.strip() for t in raw_tools.split(",") if t.strip()}
    else:
        fm["tools"] = {str(t).strip() for t in raw_tools if t}
    return fm


def test_setup_commands_bind_to_setup_assistant_policy_island() -> None:
    for command_path in COMMAND_PATHS:
        content = _read(command_path)
        assert (
            "context: brainpalace" in content
        ), f"Missing context: brainpalace in {command_path}"
        assert (
            "agent: setup-assistant" in content
        ), f"Missing agent: setup-assistant in {command_path}"


def test_config_uses_direct_setup_check_script_call() -> None:
    content = _read(CONFIG_COMMAND_PATH)

    assert 'SETUP_STATE=$(bash "$SCRIPT")' not in content
    assert 'SETUP_STATE=$("$SCRIPT")' in content


def test_install_references_script_backed_helpers() -> None:
    content = _read(INSTALL_COMMAND_PATH)

    assert "bp-pypi-version.sh" in content
    assert "bp-uv-check.sh" in content


def test_helper_scripts_exist_and_are_executable() -> None:
    assert PYPI_VERSION_SCRIPT_PATH.exists()
    assert UV_CHECK_SCRIPT_PATH.exists()
    assert PYPI_VERSION_SCRIPT_PATH.stat().st_mode & 0o111
    assert UV_CHECK_SCRIPT_PATH.stat().st_mode & 0o111


# ---------------------------------------------------------------------------
# Agent confinement — security boundary tests (Phase C, Tasks 7–8)
# ---------------------------------------------------------------------------


def test_graph_triplet_extractor_is_tool_confined() -> None:
    """graph-triplet-extractor must be confined to extraction MCP tools only.

    Security boundary: chunk text is arbitrary third-party content that the user
    did not author. Bash/Read/Write/Web access would let hostile chunk content
    escape the agent sandbox.  The only permitted tools are extraction_fetch
    (fetch own text by id) and extraction_submit (write triplets back).
    """
    fm = _frontmatter("agents/graph-triplet-extractor.md")
    tools = fm["tools"]
    assert (
        tools
    ), "tools must not be empty — extraction_fetch and extraction_submit are required"
    assert tools <= {
        "extraction_fetch",
        "extraction_submit",
    }, (
        "graph-triplet-extractor must only have extraction_fetch and "
        f"extraction_submit; got {tools!r}"
    )
    assert "Bash" not in tools, "Bash must not be in graph-triplet-extractor tools"
    assert "Read" not in tools, "Read must not be in graph-triplet-extractor tools"
    assert "Write" not in tools, "Write must not be in graph-triplet-extractor tools"


def test_chat_session_extractor_submits_via_extraction_submit() -> None:
    """chat-session-extractor must submit via extraction_submit MCP tool.

    The agent keeps Read/Glob/Bash for session-path discovery and transcript
    reading, but its submit step must use extraction_submit (not
    brainpalace submit-session) so all extraction flows share one submit path.
    """
    fm = _frontmatter("agents/chat-session-extractor.md")
    tools = fm["tools"]
    assert (
        "extraction_submit" in tools
    ), "chat-session-extractor must include extraction_submit in tools"
    assert "Read" in tools, "chat-session-extractor must keep Read"
    assert "Glob" in tools, "chat-session-extractor must keep Glob"
    assert "Bash" in tools, "chat-session-extractor must keep Bash for session-path"
    # Body must reference extraction_submit for the submit step
    content = _read(PLUGIN_DIR / "agents" / "chat-session-extractor.md")
    assert (
        "extraction_submit" in content
    ), "chat-session-extractor body must reference extraction_submit in its submit step"
    assert (
        "submit-session" not in content
    ), "chat-session-extractor must no longer reference brainpalace submit-session"


# ---------------------------------------------------------------------------
# Least-privilege setup permission bootstrap (finding 1)
# ---------------------------------------------------------------------------

SETTINGS_TEMPLATE_PATH = PLUGIN_DIR / "templates" / "settings.json"
SETUP_COMMAND_PATH = PLUGIN_DIR / "commands" / "brainpalace-setup.md"

#: Patterns that grant arbitrary execution, egress, or unscoped file ops —
#: none of these may ever appear in the shipped permission bootstrap.
BROAD_BASH_PATTERNS = {
    "Bash(bash:*)",
    "Bash(sh:*)",
    "Bash(python:*)",
    "Bash(python3:*)",
    "Bash(pip:*)",
    "Bash(pipx:*)",
    "Bash(uv:*)",
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(chmod:*)",
    "Bash(mv:*)",
    "Bash(mkdir:*)",
    "Bash(cat:*)",
    "Bash(jq:*)",
    "Bash(find:*)",
    "Bash(grep:*)",
    "Bash(rg:*)",
    "Bash(wc:*)",
    "Bash(docker:*)",
    "Bash(ollama:*)",
}


def test_settings_template_has_no_arbitrary_execution_allows() -> None:
    data = json.loads(SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8"))
    allow = set(data["permissions"]["allow"])
    assert not (
        allow & BROAD_BASH_PATTERNS
    ), f"broad patterns present: {sorted(allow & BROAD_BASH_PATTERNS)}"
    assert "Bash(brainpalace:*)" in allow


def test_setup_wizard_step0_is_consent_gated_and_minimal() -> None:
    content = _read(SETUP_COMMAND_PATH)
    for pat in sorted(BROAD_BASH_PATTERNS):
        assert f'"{pat}"' not in content, f"wizard still writes {pat}"
    assert "AskUserQuestion" in content, "Step 0 must ask before writing settings"
    assert "always available without a permission gate" not in content
    assert "safe to commit" not in content


# ---------------------------------------------------------------------------
# Agent tool confinement via the honored `tools:` key (finding 2)
# ---------------------------------------------------------------------------


def test_setup_assistant_tools_key_is_honored() -> None:
    """`allowed_tools:` is not a Claude Code agent key — the agent silently got
    ALL tools. Confinement must use the honored `tools:` key."""
    fm = _frontmatter("agents/setup-assistant.md")
    assert fm["tools"] == {"Read", "Glob", "Bash", "Write", "Edit"}
    assert "allowed_tools:" not in _read(AGENT_PATH)


def test_search_assistant_is_tool_confined() -> None:
    fm = _frontmatter("agents/search-assistant.md")
    assert fm["tools"] == {"Bash", "Read"}


def test_memory_curator_is_tool_confined() -> None:
    fm = _frontmatter("agents/memory-curator.md")
    assert fm["tools"] == {"Bash", "Read", "Glob"}
