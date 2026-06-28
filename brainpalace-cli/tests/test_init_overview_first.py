"""Task 4 tests: grid-first fresh init — review grid runs BEFORE consent wall.

The three invariants (fixed, do not weaken):
  1. Grid shown before any consent-field text on a fresh interactive run.
  2. Accepting the grid with no edits leaves billable opt-ins OFF.
  3. --yes path is non-interactive and never shows the grid.
"""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands import init as initmod

# Minimal merged config for tests: opt-in fields (sessions, git) OFF so the
# test does not depend on the developer's real global config having them on.
_CLEAN_MERGED: dict = {
    "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
    "summarization": {"provider": "openai", "model": "gpt-5-mini"},
    "session_indexing": {"enabled": False, "archive": {"enabled": True}},
    "session_extraction": {"mode": "off"},
    "git_indexing": {"enabled": False},
    "extraction": {"mode": "off"},
    "reranker": {"enabled": False},
    "graphrag": {"enabled": True},
}


def _invoke(tmp_path, monkeypatch, *, args, stdin):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(
        initmod, "_preview_embedding", lambda root: ("openai", "text-embedding-3-large")
    )
    monkeypatch.setattr(
        initmod, "_preview_merged_config", lambda root: dict(_CLEAN_MERGED)
    )
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    return CliRunner().invoke(
        initmod.init_command, ["--path", str(tmp_path), *args], input=stdin
    )


def test_fresh_init_shows_grid_before_any_consent(tmp_path, monkeypatch):
    """The review grid ([C]ontinue prompt) must appear BEFORE any consent text."""
    # Accept the grid (c), then accept the Proceed gate (y).
    r = _invoke(tmp_path, monkeypatch, args=["--no-start"], stdin="c\ny\n")
    assert r.exit_code == 0, r.output
    out = r.output
    # Grid control prompt must appear.
    assert "[C]ontinue" in out, f"Grid '[C]ontinue' not found in:\n{out}"
    # If any consent text appears it must come AFTER the grid.
    if "Embed chat sessions" in out:
        assert out.index("[C]ontinue") < out.index(
            "Embed chat sessions"
        ), "Grid appeared AFTER consent text — order is wrong"
    if "Summarize chat sessions?" in out:
        assert out.index("[C]ontinue") < out.index(
            "Summarize chat sessions?"
        ), "Grid appeared AFTER summarize consent"


def test_fresh_init_accept_grid_writes_opt_in_off(tmp_path, monkeypatch):
    """Accepting the grid with no edits leaves billable consent fields OFF."""
    # Accept the grid (c), then accept the Proceed gate (y).
    r = _invoke(tmp_path, monkeypatch, args=["--no-start"], stdin="c\ny\n")
    assert r.exit_code == 0, r.output
    cfg_path = tmp_path / ".brainpalace" / "config.yaml"
    assert cfg_path.exists(), f"config.yaml not written. Output:\n{r.output}"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    # session embedding (paid) must be OFF on plain accept.
    assert (
        cfg.get("session_indexing", {}).get("enabled", False) is False
    ), f"session_indexing.enabled was unexpectedly ON: {cfg}"
    # git indexing must be OFF on plain accept.
    assert (
        cfg.get("git_indexing", {}).get("enabled", False) is False
    ), f"git_indexing.enabled was unexpectedly ON: {cfg}"


def test_yes_run_is_non_interactive_no_grid(tmp_path, monkeypatch):
    """--yes path is non-interactive: no review grid, no [C]ontinue."""
    r = _invoke(tmp_path, monkeypatch, args=["--yes", "--no-start"], stdin="")
    assert r.exit_code == 0, r.output
    assert (
        "[C]ontinue" not in r.output
    ), f"Grid shown on --yes run (must not be). Output:\n{r.output}"
