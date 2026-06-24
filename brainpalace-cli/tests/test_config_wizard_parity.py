from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.config import config_group


def test_wizard_writes_sessions_archive_git_reranker(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    # Align the stdin order with the wizard prompt order when implementing.
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        runner.invoke(
            config_group,
            ["wizard", "--global"],
            input="openai\ntext-embedding-3-large\nopenai\n"
            "gpt-4o-mini\n1\n"  # graphrag_mode=1 (off)
            "y\ny\n0.8\n"  # compute_on, record_extraction_on, min_confidence
            "n\nn\nn\ny\n"  # sessions n, archive n, git n, reranker y
            "n\n"  # lemma=n
            "1\n8000\n"  # deployment + port
            "y\n8787\n",  # dashboard autostart + port (global only)
        )
    cfg = yaml.safe_load((Path(tmp_path) / "brainpalace" / "config.yaml").read_text())
    assert cfg["session_indexing"]["enabled"] is False
    assert cfg["session_indexing"]["archive"]["enabled"] is False
    assert cfg["git_indexing"]["enabled"] is False
    assert cfg["reranker"]["enabled"] is True
    assert cfg["compute"]["enabled"] is True
    assert cfg["compute"]["record_extraction"] is True
    assert cfg["compute"]["min_confidence"] == 0.8
    # reranker=yes opts into the local cross-encoder → installs the heavy extra
    # (graphrag mode 1 adds none).
    ensure.assert_called_once_with("reranker-local", assume_yes=True)


def test_wizard_lemma_yes_writes_engine_and_installs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        runner.invoke(
            config_group,
            ["wizard", "--global"],
            input="openai\ntext-embedding-3-large\nopenai\n"
            "gpt-4o-mini\n1\n"  # graphrag_mode=1 (off)
            "y\ny\n0.8\n"  # compute_on, record_extraction_on, min_confidence
            "n\nn\nn\nn\n"  # sessions n, archive n, git n, reranker n (isolate lemma)
            "y\n"  # lemma=y
            "1\n8000\n"  # deployment + port
            "y\n8787\n",  # dashboard autostart + port (global only)
        )
    cfg = yaml.safe_load((Path(tmp_path) / "brainpalace" / "config.yaml").read_text())
    assert cfg["bm25"]["engine"] == "lemma"
    assert cfg["compute"]["enabled"] is True
    assert cfg["compute"]["record_extraction"] is True
    ensure.assert_called_once_with("lemma-hr", assume_yes=True)


def test_wizard_lemma_no_writes_stem_and_skips_install(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        runner.invoke(
            config_group,
            ["wizard", "--global"],
            input="openai\ntext-embedding-3-large\nopenai\n"
            "gpt-4o-mini\n1\n"  # graphrag_mode=1 (off)
            "y\ny\n0.8\n"  # compute_on, record_extraction_on, min_confidence
            "n\nn\nn\nn\n"  # sessions n, archive n, git n, reranker n
            "n\n"  # lemma=n
            "1\n8000\n"  # deployment + port
            "y\n8787\n",  # dashboard autostart + port (global only)
        )
    cfg = yaml.safe_load((Path(tmp_path) / "brainpalace" / "config.yaml").read_text())
    assert cfg["bm25"]["engine"] == "stem"
    assert cfg["compute"]["enabled"] is True
    assert cfg["compute"]["record_extraction"] is True
    ensure.assert_not_called()
