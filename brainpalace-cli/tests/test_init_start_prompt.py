"""A bare interactive `init` (no --start/--no-start) asks an explicit
"Start the BrainPalace server now?" — declining it does not start the server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod


def _invoke(tmp_path: Path, monkeypatch, input_str: str):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    # Never actually launch a server if the prompt is answered yes.
    with patch.object(initmod, "_start_and_watch", return_value=[]) as start_mock:
        args = [
            "--path",
            str(tmp_path),
            "--no-extract",
            "--no-sessions",
            "--no-archive",
            "--no-git-history",
            "--no-graphrag-extract",
        ]
        result = CliRunner().invoke(initmod.init_command, args, input=input_str)
    return result, start_mock


def test_bare_init_asks_start_question_and_decline_skips_start(tmp_path, monkeypatch):
    # Prompt order on a bare fresh interactive init (the session/archive/etc. flags
    # suppress their prompts): index-target picker (folder=., type=both), reranker? n,
    # lemma? n, review=C, Estimate first? n, Start server now? n. Extra trailing
    # declines are harmless (ignored).
    result, start_mock = _invoke(
        tmp_path, monkeypatch, input_str=".\nboth\nn\nn\nc\nn\nn\n"
    )
    assert result.exit_code == 0, result.output
    assert "Start the BrainPalace server now?" in result.output
    start_mock.assert_not_called()
