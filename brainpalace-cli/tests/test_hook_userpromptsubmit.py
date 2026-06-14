"""Tests for the UserPromptSubmit drain hook (`brainpalace hook userpromptsubmit`).

Ported from the former fat bash hook: selection/throttling lives in
``drain-queue`` (tested separately), so here we stub ``drain_queue`` and assert
the hook's gating, directive text, and fail-soft contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands import hook, session_drain

REPO = Path(__file__).resolve().parents[2]


def _patch(monkeypatch, *, result, root: Path | None = Path("/tmp/proj")):
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: root)
    monkeypatch.setattr(session_drain, "resolve_budget", lambda r: 1)
    monkeypatch.setattr(session_drain, "resolve_max_count", lambda r: 1)
    monkeypatch.setattr(session_drain, "resolve_cooldown", lambda r: 0)
    if isinstance(result, Exception):

        def _boom(*_a, **_k):
            raise result

        monkeypatch.setattr(session_drain, "drain_queue", _boom)
    else:
        monkeypatch.setattr(session_drain, "drain_queue", lambda *a, **k: result)


def _run() -> str:
    return CliRunner().invoke(cli, ["hook", "userpromptsubmit"], input="{}").output


def test_drained_injects_directive(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, result={"drained": ["s1", "s2"], "remaining": 3})
    out = json.loads(_run())
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    ctx = hso["additionalContext"]
    assert "s1 s2" in ctx
    assert "chat-session-extractor" in ctx
    assert "brainpalace submit-session" in ctx
    assert "(3 more queued" in ctx


def test_remaining_zero_has_no_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, result={"drained": ["s1"], "remaining": 0})
    ctx = json.loads(_run())["hookSpecificOutput"]["additionalContext"]
    assert "more queued" not in ctx


def test_empty_drain_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, result={"drained": [], "remaining": 0, "cooldown_active": True})
    assert _run().strip() == ""


def test_non_indexed_project_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    # discover_project_dir → None means no .brainpalace/: never touch the project.
    _patch(monkeypatch, result={"drained": ["s1"], "remaining": 0}, root=None)
    assert _run().strip() == ""


def test_never_blocks_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, result=RuntimeError("boom"))
    runner = CliRunner()
    res = runner.invoke(cli, ["hook", "userpromptsubmit"], input="{}")
    assert res.exit_code == 0 and res.output.strip() == ""


def test_shim_is_thin_and_delegates() -> None:
    shim = REPO / "brainpalace-plugin" / "hooks" / "userpromptsubmit-drain-hook.sh"
    text = shim.read_text()
    assert "brainpalace hook userpromptsubmit" in text  # delegates to CLI
    assert "additionalContext" not in text  # no fat logic / injected text in shim
    assert "python3" not in text  # no inline heredoc


def test_plugin_json_registers_userpromptsubmit() -> None:
    plugin = REPO / "brainpalace-plugin" / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text())
    cmd = json.dumps(data["hooks"]["UserPromptSubmit"])
    assert "userpromptsubmit-drain-hook.sh" in cmd
