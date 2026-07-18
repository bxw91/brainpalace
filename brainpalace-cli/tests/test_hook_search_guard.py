"""Tests for the PreToolUse search guard (`brainpalace hook pretooluse`).

Sibling to the subagent guard: where that gates Agent/Task *spawns*, this gates
the main thread's own `Grep` calls so it searches via BrainPalace instead of
grep by habit. ON by default in `enforce` mode (advisory is the opt-out
softening), engages only while the project's BrainPalace server is running, and
fails open. The guard is scope-aware on every path: only a search of
manifest-indexed content with a pattern BM25 can answer faithfully reacts; Glob
is not guarded at all (a glob is a filename matcher — no correct BM25 mapping
exists).
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


def _grep_payload(proj: Path, pattern: str, path: str | None = None) -> dict:
    ti: dict = {"pattern": pattern}
    if path is not None:
        ti["path"] = path
    return {"tool_name": "Grep", "tool_input": ti, "cwd": str(proj)}


def test_grep_advisory_nudges_not_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_grep_payload(proj, "Next steps", "src"), _ADVISORY, monkeypatch)
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in hso  # advisory never denies
    assert "brainpalace query" in hso["additionalContext"]


def test_grep_enforce_denies_indexed_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_grep_payload(proj, "foo", "src"), _ENFORCE, monkeypatch)
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "brainpalace query" in hso["permissionDecisionReason"]


def test_grep_no_path_defaults_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_grep_payload(proj, "foo"), _ENFORCE, monkeypatch)
    assert json.loads(res.output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_grep_unindexed_target_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # skip/ exists on disk but is absent from the manifest -> native Grep is fine.
    proj = _bash_project(tmp_path)
    (proj / "skip").mkdir()
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_grep_payload(proj, "foo", "skip"), _ENFORCE, monkeypatch)
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_grep_regex_construct_pattern_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The Grep tool pattern is ALWAYS a ripgrep regex; BM25 cannot honor \d+,
    # so steering toward it would be wrong advice — native Grep is authoritative.
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _grep_payload(proj, r"except.*EngineError", "src"), _ENFORCE, monkeypatch
    )
    assert res.output.strip() == ""


def test_glob_is_never_guarded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Version-skew tolerance: an old plugin still matches Glob and sends the
    # payload; the CLI must stay silent — a glob is a filename matcher, BM25 a
    # content index, no correct query mapping exists.
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        {"tool_name": "Glob", "tool_input": {"pattern": "**/*.tsx"}, "cwd": str(proj)},
        _ENFORCE,
        monkeypatch,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def _bash_project(tmp_path: Path) -> Path:
    """Project fixture with one indexed file recorded in a folder manifest."""
    a = tmp_path / "src" / "a.py"
    a.parent.mkdir(parents=True)
    a.write_text("x = 1\n")
    manifests = tmp_path / ".brainpalace" / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "m.json").write_text(json.dumps({"files": {str(a.resolve()): {}}}))
    return tmp_path


def _bash_payload(proj: Path, command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(proj)}


def test_bash_recursive_grep_indexed_advisory_nudges(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, "grep -rn foo src/"), _ADVISORY, monkeypatch)
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert "permissionDecision" not in hso  # advisory never denies
    assert "brainpalace query" in hso["additionalContext"]


def test_bash_enforce_pure_search_denies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _bash_payload(proj, "grep -rn foo src/ | head -5"), _ENFORCE, monkeypatch
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "brainpalace query" in hso["permissionDecisionReason"]


def test_bash_enforce_compound_side_effect_downgrades_to_nudge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Denying `grep && make test` would block make too — spec D4 downgrades.
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _bash_payload(proj, "grep -rn foo src/ && make test"), _ENFORCE, monkeypatch
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert "permissionDecision" not in hso
    assert "brainpalace query" in hso["additionalContext"]


def test_bash_unindexed_target_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # skip/ exists on disk but is absent from the manifest -> escape hatch.
    proj = _bash_project(tmp_path)
    (proj / "skip").mkdir()
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, "grep -rn foo skip/"), _ENFORCE, monkeypatch)
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_bash_non_search_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, "ls -la src/"), _ENFORCE, monkeypatch)
    assert res.output.strip() == ""


def test_bash_single_file_grep_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Non-recursive grep of one known file is a line lookup, not a search (D3).
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, "grep -n foo src/a.py"), _ENFORCE, monkeypatch)
    assert res.output.strip() == ""


def test_bash_regex_construct_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # BM25 cannot honor \d+ — nudging toward it would be wrong advice (D3).
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, r"grep -rn '\d+' src/"), _ENFORCE, monkeypatch)
    assert res.output.strip() == ""


def test_bash_server_down_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _bash_payload(proj, "grep -rn foo src/"), _ENFORCE, monkeypatch, server_up=False
    )
    assert res.output.strip() == ""


def _register_own_guard(proj: Path) -> None:
    """Simulate a project that ships its own search-guard hook (the BrainPalace
    repo itself is the known case): committed .claude/settings.json registers
    pretooluse-brainpalace-search-guard.sh on PreToolUse."""
    claude = proj / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        'bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/'
                                        'pretooluse-brainpalace-search-guard.sh"'
                                    ),
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )


def test_bash_stands_down_when_project_ships_own_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A project registering its own search-guard hook must never double-fire
    # with the shipped guard — silent even in enforce on an indexed target.
    proj = _bash_project(tmp_path)
    _register_own_guard(proj)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(_bash_payload(proj, "grep -rn foo src/"), _ENFORCE, monkeypatch)
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_grep_stands_down_when_project_ships_own_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Standdown covers the whole search guard (Grep/Glob too), fixing the
    # pre-existing Grep double-fire in the BrainPalace repo as well.
    proj = _bash_project(tmp_path)
    _register_own_guard(proj)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        {"tool_name": "Grep", "tool_input": {"pattern": "foo"}}, _ENFORCE, monkeypatch
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_search_server_down_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _grep_payload(proj, "foo", "src"),
        _ENFORCE,
        monkeypatch,
        server_up=False,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_search_disabled_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    res = _run(
        _grep_payload(proj, "foo", "src"),
        {"enabled": False, "mode": "enforce"},
        monkeypatch,
    )
    assert res.exit_code == 0
    assert res.output.strip() == ""


def test_default_search_guard_is_on_and_enforce() -> None:
    # Enforce is safe as the shipped default now that every path is scope-aware:
    # only indexed content + a BM25-answerable pattern (+ pure Bash search)
    # fires. Advisory is the documented softening knob.
    assert hook._SEARCH_GUARD_DEFAULTS["enabled"] is True
    assert hook._SEARCH_GUARD_DEFAULTS["mode"] == "enforce"


def test_search_default_denies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # With the shipped default (no cfg stub), an indexed-target Grep is DENIED.
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x")
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    monkeypatch.setattr(hook, "_guard_config_sources", lambda: [])
    monkeypatch.delenv("BRAINPALACE_SEARCH_GUARD", raising=False)
    runner = CliRunner()
    res = runner.invoke(
        cli, ["hook", "pretooluse"], input=json.dumps(_grep_payload(proj, "x", "src"))
    )
    hso = json.loads(res.output)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"


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
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    payload = _grep_payload(proj, "foo", "src")
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
    proj = _bash_project(tmp_path)
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: proj)
    payload = _grep_payload(proj, "foo", "src")
    for _ in range(2):
        res = _run(payload, _ENFORCE, monkeypatch)
        assert '"permissionDecision": "deny"' in res.output
