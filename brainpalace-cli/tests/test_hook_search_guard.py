"""Tests for the PreToolUse search guard (`brainpalace hook pretooluse`).

Sibling to the subagent guard: where that gates Agent/Task *spawns*, this gates
the main thread's own `Grep`/`Glob` calls so it searches via BrainPalace instead
of grep/glob by habit. ON by default (`cli.search_guard.enabled`) in `advisory`
mode (enforce is opt-in), engages only while the project's BrainPalace server is
running, and fails open. `Bash` is intentionally NOT guarded — firing on every
shell command is too costly, and dropping to Bash grep/find is the deliberate
escape hatch for raw search of non-indexed files.
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
            monkeypatch.setattr(hook, "_load_search_guard_config", lambda: cfg)
    runner = CliRunner()
    return runner.invoke(cli, ["hook", "pretooluse"], input=json.dumps(payload))


_ENFORCE = {"enabled": True, "mode": "enforce"}
_ADVISORY = {"enabled": True, "mode": "advisory"}


def test_grep_advisory_nudges_not_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Fresh tmp_path project so the advisory cooldown stamp can't already be hot
    # from another test/run sharing the real project's .brainpalace dir.
    (tmp_path / ".brainpalace").mkdir()
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: tmp_path)
    res = _run(
        {"tool_name": "Grep", "tool_input": {"pattern": "Next steps"}},
        _ADVISORY,
        monkeypatch,
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hso  # advisory never denies
    assert "brainpalace query" in hso["additionalContext"]


def test_grep_enforce_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Grep", "tool_input": {"pattern": "foo"}}, _ENFORCE, monkeypatch
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "brainpalace query" in hso["permissionDecisionReason"]


def test_glob_enforce_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Glob", "tool_input": {"pattern": "**/*.tsx"}},
        _ENFORCE,
        monkeypatch,
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"


def test_bash_not_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bash is the escape hatch: a raw `grep` via Bash must pass untouched even in
    # enforce, so the model can search non-indexed files when it must.
    res = _run(
        {"tool_name": "Bash", "tool_input": {"command": "grep -r foo ."}},
        _ENFORCE,
        monkeypatch,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_search_server_down_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Grep", "tool_input": {"pattern": "foo"}},
        _ENFORCE,
        monkeypatch,
        server_up=False,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_search_disabled_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _run(
        {"tool_name": "Grep", "tool_input": {"pattern": "foo"}},
        {"enabled": False, "mode": "enforce"},
        monkeypatch,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_default_search_guard_is_on_and_advisory() -> None:
    # On by default but advisory (nudge, never deny) — an on-by-default guard must
    # not silently block every Grep/Glob for all users; enforce is opt-in.
    assert hook._SEARCH_GUARD_DEFAULTS["enabled"] is True
    assert hook._SEARCH_GUARD_DEFAULTS["mode"] == "advisory"


def test_search_default_nudges_not_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With the shipped default (no cfg stub), a Grep is NUDGED, never DENIED.
    # Fresh tmp_path project so the advisory cooldown stamp can't already be hot
    # from another test/run sharing the real project's .brainpalace dir.
    (tmp_path / ".brainpalace").mkdir()
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x")
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: tmp_path)
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.delenv("BRAINPALACE_SEARCH_GUARD", raising=False)
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["hook", "pretooluse"],
        input=json.dumps({"tool_name": "Grep", "tool_input": {"pattern": "x"}}),
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert "permissionDecision" not in hso
    assert "brainpalace query" in hso["additionalContext"]


def test_search_malformed_stdin_is_silent() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "pretooluse"], input="not json{")
    assert res.exit_code == 0
    assert res.output.strip() == ""


# --- config resolution ----------------------------------------------------


def test_search_env_override_off_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook,
        "_guard_config_sources",
        lambda: [{"cli": {"search_guard": {"enabled": True, "mode": "enforce"}}}],
    )
    monkeypatch.setenv("BRAINPALACE_SEARCH_GUARD", "off")
    assert hook._load_search_guard_config()["enabled"] is False


def test_search_env_override_enforce_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.setenv("BRAINPALACE_SEARCH_GUARD", "enforce")
    cfg = hook._load_search_guard_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "enforce"


def test_search_project_config_overrides_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAINPALACE_SEARCH_GUARD", raising=False)
    monkeypatch.setattr(
        hook,
        "_guard_config_sources",
        lambda: [
            {"cli": {"search_guard": {"enabled": False, "mode": "enforce"}}},  # global
            {"cli": {"search_guard": {"enabled": True, "mode": "advisory"}}},  # project
        ],
    )
    cfg = hook._load_search_guard_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "advisory"


def test_search_config_sources_reads_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (xdg / "config.yaml").write_text(
        yaml.safe_dump({"cli": {"search_guard": {"enabled": True}}})
    )
    proj = tmp_path / "proj"
    (proj / ".brainpalace").mkdir(parents=True)
    (proj / ".brainpalace" / "config.yaml").write_text(
        yaml.safe_dump({"cli": {"search_guard": {"mode": "advisory"}}})
    )
    monkeypatch.setattr(hook, "get_xdg_config_dir", lambda: xdg)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    cfg = hook._load_search_guard_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "advisory"


# --- advisory nudge cooldown -----------------------------------------------


def test_advisory_nudge_respects_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".brainpalace").mkdir()
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: tmp_path)
    payload = {"tool_name": "Grep", "tool_input": {"pattern": "foo"}}
    first = _run(payload, _ADVISORY, monkeypatch)
    assert "additionalContext" in first.output
    # second call inside the same run reuses the monkeypatched server/config —
    # only the stamp file on disk should change, so invoke without re-stubbing.
    runner = CliRunner()
    second = runner.invoke(cli, ["hook", "pretooluse"], input=json.dumps(payload))
    assert second.output.strip() == ""  # inside the cooldown window → silent


def test_enforce_mode_ignores_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".brainpalace").mkdir()
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: tmp_path)
    payload = {"tool_name": "Grep", "tool_input": {"pattern": "foo"}}
    for _ in range(2):
        res = _run(payload, _ENFORCE, monkeypatch)
        assert '"permissionDecision": "deny"' in res.output
