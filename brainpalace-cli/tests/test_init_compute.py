"""`brainpalace init` no longer has any compute interaction.

Compute query mode has no switches and records are extracted whenever session
extraction runs, so init neither asks about compute nor writes a `compute:`
block, and the `--compute/--no-compute` flag is gone.
"""

from pathlib import Path

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _invoke(tmp_path, monkeypatch, args):
    """Non-interactive init (no TTY → no prompts) with required monkeypatches."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    return CliRunner().invoke(initmod.init_command, args)


def test_default_init_writes_no_compute_block(tmp_path, monkeypatch):
    result = _invoke(tmp_path, monkeypatch, ["--path", str(tmp_path), "--no-start"])
    assert result.exit_code == 0, result.output
    assert "compute" not in _read(tmp_path / ".brainpalace")


def test_no_compute_flag_is_removed(tmp_path, monkeypatch):
    result = _invoke(
        tmp_path, monkeypatch, ["--path", str(tmp_path), "--no-start", "--no-compute"]
    )
    assert result.exit_code != 0
    assert "no such option" in result.output.lower()
