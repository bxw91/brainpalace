"""Tests for the UserPromptSubmit drain hook (`brainpalace hook userpromptsubmit`).

Selection/throttling/directive-building live in ``extraction_drain.unified_drain``
(tested in ``test_unified_drain.py``), so here we stub ``unified_drain`` and assert
the hook's gating (indexed project + live server), injection, and fail-soft
contract. The hook is a thin shim — its job is wiring, not text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands import extraction_drain, hook

REPO = Path(__file__).resolve().parents[2]


def _patch(
    monkeypatch,
    *,
    result,
    root: Path | None = Path("/tmp/proj"),
    url: str | None = "http://x",
):
    monkeypatch.setattr(hook, "discover_project_dir", lambda _=None: root)
    monkeypatch.setattr(hook, "discover_server_url", lambda _=None: url)
    monkeypatch.setattr(extraction_drain, "resolve_budget", lambda r: 1)
    monkeypatch.setattr(extraction_drain, "resolve_doc_cap", lambda r: 4)
    monkeypatch.setattr(extraction_drain, "resolve_session_cap", lambda r: 2)
    monkeypatch.setattr(extraction_drain, "resolve_cooldown", lambda r: 0)
    monkeypatch.setattr(extraction_drain, "resolve_max_pending", lambda r: 0)
    if isinstance(result, Exception):

        def _boom(*_a, **_k):
            raise result

        monkeypatch.setattr(extraction_drain, "unified_drain", _boom)
    else:
        monkeypatch.setattr(extraction_drain, "unified_drain", lambda *a, **k: result)


def _run() -> str:
    return CliRunner().invoke(cli, ["hook", "userpromptsubmit"], input="{}").output


def test_drained_injects_directive(monkeypatch: pytest.MonkeyPatch) -> None:
    directive = (
        "Pending extraction (best-effort):\n"
        "- doc chunks ['c1'] → ONE graph-triplet-extractor\n"
        "- sessions  ['s1', 's2'] → one chat-session-extractor PER session\n"
        "Each agent fetches its own content via the extraction tools."
    )
    _patch(
        monkeypatch,
        result={
            "directive": directive,
            "doc_ids": ["c1"],
            "session_ids": ["s1", "s2"],
        },
    )
    out = json.loads(_run())
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    ctx = hso["additionalContext"]
    assert ctx == directive
    assert "graph-triplet-extractor" in ctx
    assert "chat-session-extractor" in ctx
    # The hook injects exactly what unified_drain built — ids only, no chunk text.


def test_empty_drain_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(
        monkeypatch,
        result={"directive": None, "doc_ids": [], "session_ids": []},
    )
    assert _run().strip() == ""


def test_non_indexed_project_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    # discover_project_dir → None means no .brainpalace/: never touch the project.
    _patch(
        monkeypatch,
        result={"directive": "x", "doc_ids": ["c1"], "session_ids": []},
        root=None,
    )
    assert _run().strip() == ""


def test_server_down_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    # No live server → fail open, inject nothing (the agents could not fetch).
    _patch(
        monkeypatch,
        result={"directive": "x", "doc_ids": ["c1"], "session_ids": []},
        url=None,
    )
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
