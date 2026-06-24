"""Tests for `brainpalace init` compute-mode opt-out + the sparse writer.

Compute query mode is ON by code default, so `init` keeps the project config
sparse: it persists a `compute:` block only when the user opts OUT
(`--no-compute` / an interactive "no"). A bare run inherits the default and
writes nothing.
"""

from pathlib import Path

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod
from brainpalace_cli.commands.init import write_compute_config


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _invoke(tmp_path, monkeypatch, args):
    """Non-interactive init (no TTY → no prompts) with required monkeypatches."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    return CliRunner().invoke(initmod.init_command, args)


# --- the sparse writer ------------------------------------------------------


def test_write_compute_config_noop_when_both_none(tmp_path):
    write_compute_config(tmp_path)
    assert not (tmp_path / "config.yaml").exists()


def test_write_compute_config_optout_writes_disabled(tmp_path):
    write_compute_config(tmp_path, enabled=False, record_extraction=False)
    cfg = _read(tmp_path)
    assert cfg["compute"] == {"enabled": False, "record_extraction": False}


def test_write_compute_config_preserves_other_blocks(tmp_path):
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {"graphrag": {"enabled": True}, "compute": {"min_confidence": 0.9}}
        )
    )
    write_compute_config(tmp_path, enabled=False)
    cfg = _read(tmp_path)
    assert cfg["graphrag"] == {"enabled": True}  # untouched
    # deep-merge: existing compute keys preserved, only `enabled` set
    assert cfg["compute"] == {"min_confidence": 0.9, "enabled": False}


# --- init flag behaviour ----------------------------------------------------


def test_no_compute_flag_writes_disabled(tmp_path, monkeypatch):
    result = _invoke(
        tmp_path,
        monkeypatch,
        ["--path", str(tmp_path), "--no-start", "--no-compute"],
    )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("compute", {}).get("enabled") is False
    assert cfg.get("compute", {}).get("record_extraction") is False


def test_default_init_writes_no_compute_block(tmp_path, monkeypatch):
    """Sparse invariant: compute is ON by default, so a bare init must not
    write a compute block (the key inherits global, then the code default)."""
    result = _invoke(tmp_path, monkeypatch, ["--path", str(tmp_path), "--no-start"])
    assert result.exit_code == 0, result.output
    assert "compute" not in _read(tmp_path / ".brainpalace")
