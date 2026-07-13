"""Tests for the single-source AI-guidance system.

Covers the loader/slicer (`ai_guidance.py`), the `ai-guide` command, the `hook`
dispatcher + legacy migration, the CORE byte budget, generator determinism, and
end-to-end injection (hook JSON / MCP instructions / `ai_guide` tool). See
CLAUDE.md → "AI-guidance parity".
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli import ai_guidance
from brainpalace_cli.cli import cli

# --- byte budgets: measured size + headroom (decision-critical content survives) ---
NUDGE_MAX = 750  # measured ~709 (grew with rehome/scan guidance)
CORE_MAX = 4700  # measured ~4558 (grew with rehome/scan guidance)


# --------------------------------------------------------------------------- #
# Loader / slicer
# --------------------------------------------------------------------------- #


def test_tiers_nonempty_and_nested() -> None:
    nudge, core, full = ai_guidance.nudge(), ai_guidance.core(), ai_guidance.full()
    assert nudge and core and full
    # NUDGE ⊂ CORE ⊂ FULL — each tier's text is contained in the wider one.
    assert nudge in core
    assert core in full


def test_no_marker_tokens_leak_into_output() -> None:
    for text in (ai_guidance.nudge(), ai_guidance.core(), ai_guidance.full()):
        assert "<!--CORE-->" not in text and "<!--/CORE-->" not in text
        assert "<!--NUDGE-->" not in text and "<!--/NUDGE-->" not in text


def test_core_byte_budget() -> None:
    # CORE ships on every MCP connect; NUDGE on every session start. Guard growth.
    assert len(ai_guidance.nudge().encode()) <= NUDGE_MAX
    assert len(ai_guidance.core().encode()) <= CORE_MAX


def test_meta_from_source_not_today() -> None:
    meta = ai_guidance.parse_meta()
    assert meta["version"] != "0.0.0"
    # ISO-ish date string from the source meta line, not a runtime value.
    assert meta["last_validated"].count("-") == 2


def test_render_skill_is_deterministic() -> None:
    a = ai_guidance.render(fmt="skill")
    b = ai_guidance.render(fmt="skill")
    assert a == b
    assert a.startswith("---\nname: using-brainpalace")


def test_fail_soft_on_missing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_guidance, "load_source", lambda: "")
    assert ai_guidance.nudge() == ""
    assert ai_guidance.core() == ""
    assert ai_guidance.full() == ""
    assert ai_guidance.parse_meta()["version"] == "0.0.0"


# --------------------------------------------------------------------------- #
# `ai-guide` command
# --------------------------------------------------------------------------- #


def test_ai_guide_command_tiers() -> None:
    runner = CliRunner()
    full = runner.invoke(cli, ["ai-guide", "--tier", "full"])
    nudge = runner.invoke(cli, ["ai-guide", "--tier", "nudge"])
    assert full.exit_code == 0 and nudge.exit_code == 0
    assert len(nudge.output) < len(full.output)
    assert "Mode Decision Table" in full.output


def test_ai_guide_skill_matches_render() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["ai-guide", "--format", "skill"])
    assert res.exit_code == 0
    # `skill` is emitted with nl=False so a redirect equals render() byte-for-byte.
    assert res.output == ai_guidance.render(fmt="skill")


# --------------------------------------------------------------------------- #
# `hook sessionstart` dispatcher
# --------------------------------------------------------------------------- #


def test_hook_sessionstart_indexed_server_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from brainpalace_cli.commands import hook

    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: Path("/proj"))
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: None)  # down
    # Autostart defaults ON; stub the detached spawn so the test never launches a
    # real server. Assert it fires for an indexed-but-down project.
    spawned: list[Path] = []
    monkeypatch.setattr(hook, "_spawn_autostart", lambda p: spawned.append(p))
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "sessionstart"])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert ctx == ai_guidance.nudge()  # NUDGE only when server down
    assert spawned == [Path("/proj")]  # server down + autostart on → spawn fired


def test_hook_sessionstart_autostart_disabled_no_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from brainpalace_cli.commands import hook

    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: Path("/proj"))
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: None)  # down
    monkeypatch.setenv("BRAINPALACE_SESSION_AUTOSTART", "off")
    spawned: list[Path] = []
    monkeypatch.setattr(hook, "_spawn_autostart", lambda p: spawned.append(p))
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "sessionstart"])
    assert res.exit_code == 0
    assert spawned == []  # env off → no autostart, still emits NUDGE
    assert json.loads(res.output)["hookSpecificOutput"]["additionalContext"]


def test_spawn_autostart_is_detached_fire_and_forget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from brainpalace_cli.commands import hook

    calls: list[dict] = []

    def fake_popen(argv, **kwargs):  # noqa: ANN001, ANN202
        calls.append({"argv": argv, "kwargs": kwargs})
        return object()

    monkeypatch.setattr(hook.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/brainpalace")
    hook._spawn_autostart(Path("/proj"))
    assert len(calls) == 1
    # --no-activate: a passive (hook-spawned) start must never clear the
    # activation gate marker — only a user-typed start activates a project.
    assert calls[0]["argv"] == [
        "/usr/bin/brainpalace",
        "start",
        "--json",
        "--no-activate",
    ]


def test_hook_sessionstart_server_up_resurrects_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server UP but dashboard may be dead → the hook best-effort relaunches it
    (it is launched on `brainpalace start`, not supervised)."""
    from brainpalace_cli.commands import hook

    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: Path("/proj"))
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x:8000")
    monkeypatch.setattr(hook, "_session_context_data", lambda _url: {})  # no HTTP
    monkeypatch.setattr(hook, "_dashboard_autostart_enabled", lambda: True)
    dash: list[Path] = []
    monkeypatch.setattr(hook, "_spawn_dashboard_autostart", lambda p: dash.append(p))
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "sessionstart"])
    assert res.exit_code == 0
    assert dash == [Path("/proj")]  # server up → dashboard resurrect fired


def test_hook_sessionstart_server_up_dashboard_autostart_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dashboard.autostart off → the hook does NOT relaunch the dashboard."""
    from brainpalace_cli.commands import hook

    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: Path("/proj"))
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: "http://x:8000")
    monkeypatch.setattr(hook, "_session_context_data", lambda _url: {})
    monkeypatch.setattr(hook, "_dashboard_autostart_enabled", lambda: False)
    dash: list[Path] = []
    monkeypatch.setattr(hook, "_spawn_dashboard_autostart", lambda p: dash.append(p))
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "sessionstart"])
    assert res.exit_code == 0
    assert dash == []


def test_spawn_dashboard_autostart_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    from brainpalace_cli.commands import hook

    calls: list[dict] = []

    def fake_popen(argv, **kwargs):  # noqa: ANN001, ANN202
        calls.append({"argv": argv, "kwargs": kwargs})
        return object()

    monkeypatch.setattr(hook.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(hook.shutil, "which", lambda _: "/usr/bin/brainpalace")
    hook._spawn_dashboard_autostart(Path("/proj"))
    assert calls[0]["argv"] == [
        "/usr/bin/brainpalace",
        "dashboard",
        "start",
        "--no-open",
    ]
    assert calls[0]["kwargs"]["start_new_session"] is True
    assert calls[0]["kwargs"]["cwd"] == "/proj"
    assert calls[0]["kwargs"]["start_new_session"] is True  # own session → detached
    # Never waited on (fire-and-forget): Popen handle is discarded, no .wait().


def test_hook_sessionstart_not_indexed_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from brainpalace_cli.commands import hook

    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: None)
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "sessionstart"])
    assert res.exit_code == 0
    assert res.output.strip() == ""  # non-indexed → emit nothing, never block


def test_hook_is_hidden() -> None:
    # Internal dispatcher — registered but hidden from `--help`.
    assert cli.commands["hook"].hidden is True


# --------------------------------------------------------------------------- #
# Legacy fat-hook → thin-shim migration
# --------------------------------------------------------------------------- #


def test_migration_rewrites_legacy_and_is_idempotent() -> None:
    from brainpalace_cli.commands.session_hooks import (
        migrate_legacy_sessionstart_hook,
    )

    home = Path(tempfile.mkdtemp())
    hooks = home / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "brainpalace-sessionstart.sh"
    hook.write_text("#!/bin/bash\nbrainpalace whoami\npython3 - <<'PY'\n...\nPY\n")

    assert migrate_legacy_sessionstart_hook(home) is True
    assert "brainpalace hook sessionstart" in hook.read_text()
    assert migrate_legacy_sessionstart_hook(home) is False  # idempotent


def test_migration_does_not_install_when_absent() -> None:
    from brainpalace_cli.commands.session_hooks import (
        migrate_legacy_sessionstart_hook,
    )

    home = Path(tempfile.mkdtemp())
    assert migrate_legacy_sessionstart_hook(home) is False
    assert not (home / ".claude" / "hooks" / "brainpalace-sessionstart.sh").exists()


# --------------------------------------------------------------------------- #
# E2E injection: MCP instructions + ai_guide tool
# --------------------------------------------------------------------------- #


def test_mcp_instructions_carry_core() -> None:
    from brainpalace_cli.mcp_server import server

    assert server._INSTRUCTIONS == ai_guidance.core()


def test_mcp_ai_guide_tool_returns_full() -> None:
    from brainpalace_cli.mcp_server.schemas import AiGuideInput
    from brainpalace_cli.mcp_server.tools import ai_guide_tool

    out = asyncio.run(ai_guide_tool(AiGuideInput(tier="full")))
    assert out["tier"] == "full"
    assert out["guidance"] == ai_guidance.full()
