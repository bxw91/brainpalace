import json
from pathlib import Path

from click.testing import CliRunner

from brainpalace_cli.cli import cli

REPO = Path(__file__).resolve().parents[3]


def _run(payload: dict):
    return CliRunner().invoke(cli, ["hook", "posttooluse"], input=json.dumps(payload))


def test_nudge_emitted_for_interface_source_edit():
    res = _run(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/x/brainpalace-cli/brainpalace_cli/cli.py"},
        }
    )
    assert res.exit_code == 0
    ctx = json.loads(res.output)["hookSpecificOutput"]["additionalContext"]
    assert "sync-docs" in ctx


def test_silent_for_doc_only_edit():
    res = _run(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/x/brainpalace-plugin/commands/brainpalace-query.md"
            },
        }
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""  # no nudge → no re-trigger loop


def test_never_blocks_on_garbage_input():
    res = CliRunner().invoke(cli, ["hook", "posttooluse"], input="not json")
    assert res.exit_code == 0 and res.output.strip() == ""


def test_shim_is_thin_and_delegates():
    shim = REPO / "brainpalace-plugin" / "hooks" / "posttooluse-docsync-hook.sh"
    assert shim.exists()
    text = shim.read_text()
    assert "brainpalace hook posttooluse" in text  # delegates to CLI
    assert "additionalContext" not in text  # no fat logic in the shim


def test_plugin_json_registers_posttooluse():
    plugin = REPO / "brainpalace-plugin" / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text())
    assert "PostToolUse" in data.get("hooks", {})
    cmd = json.dumps(data["hooks"]["PostToolUse"])
    assert "posttooluse-docsync-hook.sh" in cmd
