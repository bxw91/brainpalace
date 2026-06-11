"""Tests for `brainpalace init` graphrag doc-extraction question + opt-in install."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def test_decline_graphrag_extraction_writes_none_and_skips_install(
    tmp_path, monkeypatch
):
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
            # graphrag-extract=N, reranker-change=N (keep inherited), lemma=N, Proceed=Y
            input="n\nn\nn\ny\n",
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("graphrag", {}).get("doc_extractor") == "none"
    ensure.assert_not_called()


def test_enable_graphrag_extraction_writes_langextract_and_installs(
    tmp_path, monkeypatch
):
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
            # graphrag-extract=Y, reranker-change=N (keep inherited), lemma=N, Proceed=Y
            input="y\nn\nn\ny\n",
        )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("graphrag", {}).get("doc_extractor") == "langextract"
    ensure.assert_called_once_with("graphrag", assume_yes=True)


def test_no_graphrag_extract_flag_writes_none_skips_install(tmp_path):
    """--no-graphrag-extract flag (non-interactive) writes none, no install."""
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
    assert cfg.get("graphrag", {}).get("doc_extractor") == "none"
    ensure.assert_not_called()


def test_graphrag_extract_flag_writes_langextract_and_installs(tmp_path):
    """--graphrag-extract flag (non-interactive) writes langextract + installs."""
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
    assert cfg.get("graphrag", {}).get("doc_extractor") == "langextract"
    ensure.assert_called_once_with("graphrag", assume_yes=True)


def test_graphrag_extract_does_not_clobber_other_graphrag_keys(tmp_path):
    """write_graphrag_doc_extractor deep-merges; existing keys survive."""
    from brainpalace_cli.commands.init import write_graphrag_doc_extractor

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.yaml").write_text(
        "graphrag:\n  enabled: true\n  store_type: sqlite\n"
        "embedding:\n  provider: openai\n"
    )
    write_graphrag_doc_extractor(state_dir, doc_extractor="langextract")
    data = yaml.safe_load((state_dir / "config.yaml").read_text())
    assert data["graphrag"]["doc_extractor"] == "langextract"
    assert data["graphrag"]["enabled"] is True
    assert data["graphrag"]["store_type"] == "sqlite"
    assert data["embedding"]["provider"] == "openai"


def test_decline_on_existing_project_reinit_writes_none(tmp_path, monkeypatch):
    """Re-init: declining graphrag extract writes none on the existing-project path."""
    # Set up an already-initialized project
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
        # Pre-existing ⇒ keep/delete/cancel first (keep), then prompts:
        # summarize=N, embed=N, archive=N, git=N, graphrag-extract=N,
        # reranker-change=N, lemma=N, proceed=Y
        result = runner.invoke(
            initmod.init_command,
            ["--path", str(tmp_path)],
            input="keep\nn\nn\nn\nn\nn\nn\nn\ny\n",
        )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data.get("graphrag", {}).get("doc_extractor") == "none"
    ensure.assert_not_called()


def test_enable_on_existing_project_reinit_writes_langextract(tmp_path, monkeypatch):
    """Re-init: enabling graphrag extract writes langextract + installs on re-init."""
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
        # keep, summarize=N, embed=N, archive=N, git=N, graphrag-extract=Y,
        # reranker-change=N, lemma=N, proceed=Y
        result = runner.invoke(
            initmod.init_command,
            ["--path", str(tmp_path)],
            input="keep\nn\nn\nn\nn\ny\nn\nn\ny\n",
        )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data.get("graphrag", {}).get("doc_extractor") == "langextract"
    ensure.assert_called_once_with("graphrag", assume_yes=True)
