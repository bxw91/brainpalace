"""config wizard is a thin alias of init's editor — black-box equivalence tests.

Finding #10: the old mock-based parity test was unsound (it tested
implementation, not behaviour). These tests drive the CLI end-to-end:
  * wizard on a non-TTY run → init delegates cleanly (no bespoke flow)
  * wizard --global delegates to init --global
  * wizard on an initialized project with TTY → registry-driven editor
  * "Deployment mode" / bespoke prompts are gone
"""

from __future__ import annotations

import json as _json

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod
from brainpalace_cli.commands.config import config_group


def _make_initialized(tmp_path):
    """Create a minimal already-initialized project (config.json = re-init sentinel)."""
    state = tmp_path / ".brainpalace"
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.json").write_text(_json.dumps({"project_root": str(tmp_path)}))
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    return state


def test_wizard_non_tty_no_bespoke_flow(tmp_path, monkeypatch):
    """Non-interactive wizard delegates to init; no bespoke "Deployment mode" prompt."""
    monkeypatch.chdir(tmp_path)
    _make_initialized(tmp_path)
    # CliRunner is NOT a TTY → no prompts fired.
    result = CliRunner().invoke(config_group, ["wizard"])
    assert result.exit_code == 0, result.output
    assert "Deployment mode" not in result.output
    assert "Embedding provider" not in result.output  # bespoke wizard prompts gone


def test_wizard_global_no_tty_is_noop(tmp_path, monkeypatch):
    """wizard --global non-interactive → delegates to init --global → no-op (--yes)."""
    monkeypatch.setattr(
        "brainpalace_cli.xdg_paths.get_xdg_config_dir", lambda: tmp_path
    )
    result = CliRunner().invoke(config_group, ["wizard", "--global"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "config.yaml").exists()


def test_wizard_global_edits_global(tmp_path, monkeypatch):
    """wizard --global with TTY → delegates to init --global review screen."""
    monkeypatch.setattr(
        "brainpalace_cli.xdg_paths.get_xdg_config_dir", lambda: tmp_path
    )
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    result = CliRunner().invoke(config_group, ["wizard", "--global"], input="c\nn\n")
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "config.yaml").exists()  # accept, no edits → no write


def test_wizard_on_initialized_project_edits_sparsely(tmp_path, monkeypatch):
    """wizard on an initialized project with TTY → review editor, sparse write."""
    monkeypatch.chdir(tmp_path)
    state = _make_initialized(tmp_path)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    # Re-init flow (wizard passes start=False, no extra flags). Grid-first:
    #   keep (pre-existing-index prompt)
    #   grid1 (review): [C]ontinue
    #   Proceed? → Y
    #   grid2 (re-init editor): drill embedding (1), set provider=ollama, Enter
    #   past model/api_key/api_key_env/base_url/params, [C]ontinue.
    # Gate-first drill: embedding has no gates. All fields shown (incl. advanced
    # api_key_env and hidden api_key/params) — 5 fields after provider.
    result = CliRunner().invoke(
        config_group,
        ["wizard"],
        input="keep\nc\nY\n1\nollama\n\n\n\n\n\nc\n",
    )
    assert result.exit_code == 0, result.output
    assert "Deployment mode" not in result.output
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["embedding"]["provider"] == "ollama"
