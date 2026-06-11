"""Tests for `brainpalace init` session-archive opt-in question."""

from pathlib import Path

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _invoke(tmp_path, monkeypatch, args, input_str):
    """Invoke init_command with TTY simulation and required monkeypatches."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    runner = CliRunner()
    return runner.invoke(initmod.init_command, args, input=input_str)


def test_decline_archive_writes_disabled(tmp_path, monkeypatch):
    result = _invoke(
        tmp_path,
        monkeypatch,
        [
            "--path",
            str(tmp_path),
            "--no-start",
            "--no-extract",
            "--no-sessions",
            "--no-git-history",
            "--no-graphrag-extract",
        ],
        # archive: no, reranker-change: no (keep inherited), lemma: no, Proceed: yes
        input_str="n\nn\nn\ny\n",
    )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("session_indexing", {}).get("archive", {}).get("enabled") is False


def test_accept_archive_writes_enabled(tmp_path, monkeypatch):
    result = _invoke(
        tmp_path,
        monkeypatch,
        [
            "--path",
            str(tmp_path),
            "--no-start",
            "--no-extract",
            "--no-sessions",
            "--no-git-history",
            "--no-graphrag-extract",
        ],
        # archive: yes, reranker-change: no (keep inherited), lemma: no, Proceed: yes
        input_str="y\nn\nn\ny\n",
    )
    assert result.exit_code == 0, result.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("session_indexing", {}).get("archive", {}).get("enabled") is True


def test_reinit_no_start_persists_archive_decline(tmp_path, monkeypatch):
    """A --no-start re-init must persist the archive answer.

    Regression: the existing-project re-init path wrote git-history and
    graphrag choices but dropped archive (archive was only written inside the
    plan.start branch), so a --no-start re-init silently lost the answer.
    """
    common = [
        "--path",
        str(tmp_path),
        "--no-start",
        "--no-extract",
        "--no-sessions",
        "--no-git-history",
        "--no-graphrag-extract",
    ]
    # Create the project with archive ON via flag.
    # Reranker gate still fires (no --reranking/--no-reranking flag).
    # reranker-change=N, lemma=N, proceed=Y (archive suppressed by --archive flag).
    r1 = _invoke(tmp_path, monkeypatch, common + ["--archive"], input_str="n\nn\ny\n")
    assert r1.exit_code == 0, r1.output
    assert (
        _read(tmp_path / ".brainpalace")
        .get("session_indexing", {})
        .get("archive", {})
        .get("enabled")
        is True
    )
    # Re-init, decline the archive prompt → must persist False on --no-start.
    # keep existing, archive=N, reranker-change=N, lemma=N, proceed=Y.
    r2 = _invoke(tmp_path, monkeypatch, common, input_str="keep\nn\nn\nn\ny\n")
    assert r2.exit_code == 0, r2.output
    assert (
        _read(tmp_path / ".brainpalace")
        .get("session_indexing", {})
        .get("archive", {})
        .get("enabled")
        is False
    )
