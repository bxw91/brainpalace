"""Tests for the PreToolUse subagent guard (`brainpalace hook pretooluse`).

The guard gates Agent/Task spawns so subagents are forced to search via
BrainPalace. It is ON by default (`cli.subagent_guard.enabled`) in `advisory`
mode (enforce is opt-in), engages only while the project's BrainPalace server is
running, and fails open.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands import hook


def _run(payload: dict, cfg: dict | None = None, monkeypatch=None, server_up=True):
    """Invoke `hook pretooluse` with a JSON payload; optionally stub the config.

    By default pretends a live server is serving so the guard engages; pass
    ``server_up=False`` to simulate a down / absent server.
    """
    if monkeypatch is not None:
        url = "http://127.0.0.1:8000" if server_up else None
        monkeypatch.setattr(hook, "discover_server_url", lambda _=None: url)
        if cfg is not None:
            monkeypatch.setattr(hook, "_load_guard_config", lambda: cfg)
    runner = CliRunner()
    return runner.invoke(cli, ["hook", "pretooluse"], input=json.dumps(payload))


_ENFORCE = {"enabled": True, "mode": "enforce", "allow_agents": []}
_ADVISORY = {"enabled": True, "mode": "advisory", "allow_agents": []}
_GOOD_PROMPT = "Search the code: brainpalace query 'auth' --mode hybrid --top-k 8"
_BAD_PROMPT = "Go find where auth middleware lives and summarize it."


def test_non_agent_tool_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run({"tool_name": "Bash", "tool_input": {}}, _ENFORCE, monkeypatch)
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_disabled_guard_allows_bad_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"enabled": False, "mode": "enforce", "allow_agents": []}
    res = _run(
        {"tool_name": "Task", "tool_input": {"prompt": _BAD_PROMPT}}, cfg, monkeypatch
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_server_down_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": _BAD_PROMPT}},
        _ENFORCE,
        monkeypatch,
        server_up=False,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_default_config_is_on_and_advisory() -> None:
    # Default is ON but advisory (nudge, never deny) so the guard doesn't silently
    # block other plugins' agents; enforce is opt-in. See _GUARD_DEFAULTS comment.
    assert hook._GUARD_DEFAULTS["enabled"] is True
    assert hook._GUARD_DEFAULTS["mode"] == "advisory"
    assert hook._GUARD_DEFAULTS["allow_agents"] == ["research-assistant"]


def test_research_assistant_agent_allowed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Default config (no cfg stub) must not deny the shipped research agent.
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x")
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.delenv("BRAINPALACE_SUBAGENT_GUARD", raising=False)
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["hook", "pretooluse"],
        input=json.dumps(
            {
                "tool_name": "Agent",
                "tool_input": {
                    "subagent_type": "research-assistant",
                    "prompt": _BAD_PROMPT,
                },
            }
        ),
    )
    assert res.output.strip() == ""


def test_default_nudges_not_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    # With the shipped default (advisory), a non-allowlisted agent + bad prompt is
    # NUDGED, never DENIED — so other plugins' spawns are not silently blocked.
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x")
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.delenv("BRAINPALACE_SUBAGENT_GUARD", raising=False)
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["hook", "pretooluse"],
        input=json.dumps({"tool_name": "Agent", "tool_input": {"prompt": _BAD_PROMPT}}),
    )
    out = json.loads(res.output)
    hso = out["hookSpecificOutput"]
    assert "permissionDecision" not in hso  # not a denial
    assert "brainpalace query" in hso["additionalContext"]


def test_enforce_denies_missing_directive(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": _BAD_PROMPT}},
        _ENFORCE,
        monkeypatch,
    )
    out = json.loads(res.output)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "brainpalace query" in hso["permissionDecisionReason"]


def test_good_prompt_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": _GOOD_PROMPT}},
        _ENFORCE,
        monkeypatch,
    )
    assert res.output.strip() == ""


@pytest.mark.parametrize(
    "prompt",
    [
        "Use the brainpalace `query` tool with mode: hybrid to find auth.",
        "Call brainpalace query tool (mode=graph) to trace callers.",
        'Search via brainpalace: {"tool": "query", "mode": "vector"}.',
    ],
)
def test_mcp_mode_directive_allowed(
    prompt: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The MCP/skill `query` tool has no `--mode` flag; a `mode:` argument near a
    # brainpalace mention must satisfy the guard just like the CLI directive.
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": prompt}}, _ENFORCE, monkeypatch
    )
    assert res.output.strip() == ""


def test_mode_without_brainpalace_still_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bare `mode: hybrid` with no brainpalace mention is not a search directive.
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": "Render with mode: hybrid."}},
        _ENFORCE,
        monkeypatch,
    )
    out = json.loads(res.output)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_allowlisted_agent_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"enabled": True, "mode": "enforce", "allow_agents": ["research"]}
    res = _run(
        {
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "research", "prompt": _BAD_PROMPT},
        },
        cfg,
        monkeypatch,
    )
    assert res.output.strip() == ""


def test_exempt_marker_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = (
        "# BRAINPALACE_EXEMPT: pure refactor, no codebase search needed\n"
        "Rename foo to bar."
    )
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": prompt}}, _ENFORCE, monkeypatch
    )
    assert res.output.strip() == ""


def test_short_exempt_reason_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = "# BRAINPALACE_EXEMPT: too short\nDo a thing."
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": prompt}}, _ENFORCE, monkeypatch
    )
    assert json.loads(res.output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bypass_phrase_denied_despite_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "Do not use brainpalace. " + _GOOD_PROMPT
    res = _run(
        {"tool_name": "Agent", "tool_input": {"prompt": prompt}}, _ENFORCE, monkeypatch
    )
    assert json.loads(res.output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_advisory_nudges_not_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Task", "tool_input": {"prompt": _BAD_PROMPT}},
        _ADVISORY,
        monkeypatch,
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert "permissionDecision" not in hso
    assert "additionalContext" in hso


def test_malformed_stdin_is_silent() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "pretooluse"], input="not json{")
    assert res.exit_code == 0
    assert res.output.strip() == ""


# --- config resolution ----------------------------------------------------


def test_env_override_off_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook,
        "_guard_config_sources",
        lambda: [{"cli": {"subagent_guard": {"enabled": True, "mode": "enforce"}}}],
    )
    monkeypatch.setenv("BRAINPALACE_SUBAGENT_GUARD", "off")
    assert hook._load_guard_config()["enabled"] is False


def test_env_override_enforce_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.setenv("BRAINPALACE_SUBAGENT_GUARD", "enforce")
    cfg = hook._load_guard_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "enforce"


def test_project_config_overrides_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINPALACE_SUBAGENT_GUARD", raising=False)
    monkeypatch.setattr(
        hook,
        "_guard_config_sources",
        lambda: [
            {
                "cli": {"subagent_guard": {"enabled": False, "mode": "enforce"}}
            },  # global
            {
                "cli": {"subagent_guard": {"enabled": True, "mode": "advisory"}}
            },  # project
        ],
    )
    cfg = hook._load_guard_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "advisory"


def test_config_sources_reads_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        yaml.safe_dump({"cli": {"subagent_guard": {"enabled": True}}})
    )
    proj = tmp_path / "proj"
    (proj / ".brainpalace").mkdir(parents=True)
    (proj / ".brainpalace" / "config.yaml").write_text(
        yaml.safe_dump({"cli": {"subagent_guard": {"mode": "advisory"}}})
    )
    monkeypatch.setattr(hook, "get_xdg_config_dir", lambda: xdg)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    sources = hook._guard_config_sources()
    assert sources[0]["cli"]["subagent_guard"]["enabled"] is True
    assert sources[1]["cli"]["subagent_guard"]["mode"] == "advisory"
