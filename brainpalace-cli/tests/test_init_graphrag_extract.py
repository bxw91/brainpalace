"""Tests for `brainpalace init` graphrag doc-extraction question (extraction.mode)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def test_decline_graphrag_extraction_writes_off_and_skips_install(
    tmp_path, monkeypatch
):
    """Declining doc-graph extraction writes extraction.mode=off; no extra installed."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        result = runner.invoke(
            initmod.init_command,
            [
                "--path",
                str(tmp_path),
                "--no-start",
                "--no-extract",
                "--no-sessions",
                "--no-git-history",
                "--no-archive",
            ],
            # Accept the grid without touching the Extraction Engine division →
            # extraction.mode stays off; then Proceed.
            input="c\ny\n",
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("extraction", {}).get("mode") == "off"
    assert "doc_extractor" not in cfg.get("graphrag", {})
    ensure.assert_not_called()


def test_enable_graphrag_extraction_writes_subagent(tmp_path, monkeypatch):
    """Enabling doc-graph extraction writes extraction.mode=subagent (free, no dep)."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    monkeypatch.setattr(initmod, "install_session_hooks", lambda *a, **k: None)
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        result = runner.invoke(
            initmod.init_command,
            [
                "--path",
                str(tmp_path),
                "--no-start",
                "--no-extract",
                "--no-sessions",
                "--no-git-history",
                "--no-archive",
            ],
            # Drill the Extraction Engine division (14) → mode=subagent. Turning
            # the gate on reveals the 10 advanced extraction fields in the same
            # drill — Enter past each — then [C]ontinue, Proceed.
            # Grid: Extraction Engine is division 14 (after the three Chat Session
            # divisions 11-13).
            input="14\nsubagent\n" + "\n" * 10 + "c\ny\n",
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("extraction", {}).get("mode") == "subagent"
    assert "doc_extractor" not in cfg.get("graphrag", {})
    # subagent mode: no optional extra to install
    ensure.assert_not_called()


def test_no_graphrag_extract_flag_writes_off_skips_install(tmp_path):
    """--no-graphrag-extract flag (non-interactive) writes extraction.mode=off."""
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        result = runner.invoke(
            initmod.init_command,
            [
                "--path",
                str(tmp_path),
                "--no-start",
                "--json",
                "--no-graphrag-extract",
            ],
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("extraction", {}).get("mode") == "off"
    assert "doc_extractor" not in cfg.get("graphrag", {})
    ensure.assert_not_called()


def test_graphrag_extract_flag_writes_subagent(tmp_path):
    """--graphrag-extract flag (non-interactive) writes extraction.mode=subagent."""
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        result = runner.invoke(
            initmod.init_command,
            [
                "--path",
                str(tmp_path),
                "--no-start",
                "--json",
                "--graphrag-extract",
            ],
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("extraction", {}).get("mode") == "subagent"
    assert "doc_extractor" not in cfg.get("graphrag", {})
    # subagent: no extra dep needed
    ensure.assert_not_called()


def test_write_extraction_mode_does_not_clobber_other_keys(tmp_path):
    """write_extraction_mode deep-merges; existing graphrag + embedding keys survive."""
    from brainpalace_cli.commands.init import write_extraction_mode

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.yaml").write_text(
        "graphrag:\n  enabled: true\n  store_type: sqlite\n"
        "embedding:\n  provider: openai\n"
    )
    write_extraction_mode(state_dir, mode="subagent")
    data = yaml.safe_load((state_dir / "config.yaml").read_text())
    assert data["extraction"]["mode"] == "subagent"
    assert data["graphrag"]["enabled"] is True
    assert data["graphrag"]["store_type"] == "sqlite"
    assert data["embedding"]["provider"] == "openai"


def test_decline_on_existing_project_reinit_writes_off(tmp_path, monkeypatch):
    """Re-init: declining graphrag extract writes extraction.mode=off."""
    sd = tmp_path / ".brainpalace"
    sd.mkdir()
    (sd / "config.json").write_text(f'{{"project_root": "{tmp_path}"}}')
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "graphrag:\n  enabled: true\n  store_type: sqlite\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    monkeypatch.setattr(initmod, "_start_and_watch", lambda **k: [])
    monkeypatch.setattr(initmod, "install_session_hooks", lambda *a, **k: None)
    monkeypatch.setattr(initmod, "_prune_old_extraction_hooks", lambda *a, **k: None)

    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        # Pre-existing ⇒ keep/delete/cancel first (keep). Then accept the review
        # grid (don't touch the Extraction Engine division), Start gate=Y, and the
        # re-init editor grid ([C]ontinue).
        result = runner.invoke(
            initmod.init_command,
            ["--path", str(tmp_path)],
            input="keep\nc\ny\nc\n",
        )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data.get("extraction", {}).get("mode") == "off"
    assert "doc_extractor" not in data.get("graphrag", {})
    ensure.assert_not_called()


def test_enable_on_existing_project_reinit_writes_subagent(tmp_path, monkeypatch):
    """Re-init: enabling graphrag extract writes extraction.mode=subagent (free)."""
    sd = tmp_path / ".brainpalace"
    sd.mkdir()
    (sd / "config.json").write_text(f'{{"project_root": "{tmp_path}"}}')
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "graphrag:\n  enabled: true\n  store_type: sqlite\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    monkeypatch.setattr(initmod, "_start_and_watch", lambda **k: [])
    monkeypatch.setattr(initmod, "install_session_hooks", lambda *a, **k: None)
    monkeypatch.setattr(initmod, "_prune_old_extraction_hooks", lambda *a, **k: None)

    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        # keep, then in the review grid drill the Extraction Engine division (14)
        # → mode=subagent. The gate-on reveals the 10 advanced extraction fields —
        # Enter past each — then [C]ontinue, Start gate=Y, re-init grid [C]ontinue.
        # Grid: Extraction Engine is division 14 (after Chat Session divisions 11-13).
        result = runner.invoke(
            initmod.init_command,
            ["--path", str(tmp_path)],
            input="keep\n14\nsubagent\n" + "\n" * 10 + "c\ny\nc\n",
        )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data.get("extraction", {}).get("mode") == "subagent"
    assert "doc_extractor" not in data.get("graphrag", {})
    # subagent: no optional extra needed
    ensure.assert_not_called()


def test_enable_extraction_writes_only_extraction_block(tmp_path):
    from brainpalace_cli.commands import init as initmod

    initmod.write_extraction_config(tmp_path, "subagent")

    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["extraction"]["mode"] == "subagent"
    # The legacy session_extraction block must NOT be written.
    assert "mode" not in (data.get("session_extraction") or {})
