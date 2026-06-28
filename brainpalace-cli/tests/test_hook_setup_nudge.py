"""The SessionStart setup nudge offered when the CLI is present but the cwd is
not yet indexed. Conservative by design: git-repos only, once per directory,
and silenceable via ``BRAINPALACE_SETUP_NUDGE=off``.
"""

from __future__ import annotations

import json

import pytest

from brainpalace_cli.commands import hook


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Run each test in a throwaway cwd + XDG state dir, nudge enabled."""
    monkeypatch.delenv("BRAINPALACE_SETUP_NUDGE", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _capture(capsys) -> str:
    return capsys.readouterr().out.strip()


def test_nudge_in_git_repo_offers_setup(_isolate, capsys):
    (_isolate / ".git").mkdir()
    hook._maybe_emit_setup_nudge()
    payload = json.loads(_capture(capsys))
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "AskUserQuestion" in ctx
    assert "/brainpalace-setup" in ctx


def test_no_nudge_outside_git_repo(_isolate, capsys):
    # No .git → not a project root → stay silent (original no-nag behavior).
    hook._maybe_emit_setup_nudge()
    assert _capture(capsys) == ""


def test_nudge_only_once_per_directory(_isolate, capsys):
    (_isolate / ".git").mkdir()
    hook._maybe_emit_setup_nudge()
    assert _capture(capsys) != ""  # first session offers.
    hook._maybe_emit_setup_nudge()
    assert _capture(capsys) == ""  # second session for the same dir is silent.


def test_opt_out_silences_nudge(_isolate, capsys, monkeypatch):
    (_isolate / ".git").mkdir()
    monkeypatch.setenv("BRAINPALACE_SETUP_NUDGE", "off")
    hook._maybe_emit_setup_nudge()
    assert _capture(capsys) == ""
