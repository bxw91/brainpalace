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
        # Drill the Chat Session : Archiving division (10 — Indexing=8,
        # GitIndexing=9, Archiving=10): set archive Enabled=N (gate off skips its
        # sub-fields), [C]ontinue, Proceed.
        input_str="10\nn\nc\ny\n",
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
        # Drill the Chat Session : Vector Indexing division (11, after Archiving=10):
        # decline session embed consent (N), accept archive Enabled default (Y), Enter
        # past the archive sub-fields (dir/retain/reconcile), [C]ontinue, Proceed.
        # Gate-first order: session_indexing.enabled (consent) → archive.enabled.
        # With enabled=False (default), enabled-gated fields are skipped.
        # archive.enabled stays at default True, so archive sub-fields are shown.
        input_str="11\nn\n\n\n\n\nc\ny\n",
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
    # Create the project with archive ON via flag. Accept the grid ([C]ontinue),
    # then Proceed.
    r1 = _invoke(tmp_path, monkeypatch, common + ["--archive"], input_str="c\ny\n")
    assert r1.exit_code == 0, r1.output
    assert (
        _read(tmp_path / ".brainpalace")
        .get("session_indexing", {})
        .get("archive", {})
        .get("enabled")
        is True
    )
    # Re-init, decline archive via the grid → must persist False on --no-start.
    # keep; grid1 drill 10 (Chat Session : Archiving) → archive Enabled=N, [C]ontinue;
    # Proceed=Y; grid2 [C]ontinue.
    r2 = _invoke(tmp_path, monkeypatch, common, input_str="keep\n10\nn\nc\ny\nc\n")
    assert r2.exit_code == 0, r2.output
    assert (
        _read(tmp_path / ".brainpalace")
        .get("session_indexing", {})
        .get("archive", {})
        .get("enabled")
        is False
    )
