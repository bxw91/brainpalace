"""Interactive session-consent prompts during `brainpalace init`."""

from __future__ import annotations

from click.testing import CliRunner

from brainpalace_cli.commands import init as initmod


def _invoke(tmp_path, monkeypatch, *, args, stdin, plugin=True):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: plugin)
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)  # force interactive
    return CliRunner().invoke(
        initmod.init_command, ["--path", str(tmp_path), *args], input=stdin
    )


def test_prompts_shown_and_decline_is_config_only(tmp_path, monkeypatch):
    # summarize=Y, embed=N, proceed=N → config-only, but prompts were shown.
    r = _invoke(tmp_path, monkeypatch, args=[], stdin="y\nn\nn\n")
    assert r.exit_code == 0, r.output
    assert "Summarize chat sessions?" in r.output
    assert "Embed chat sessions" in r.output
    # the embed prompt names the resolved provider
    assert "OpenAI text-embedding-3-large" in r.output


def test_explicit_flags_skip_prompts(tmp_path, monkeypatch):
    # Both capabilities set by flag → no prompts; just the proceed confirm.
    r = _invoke(
        tmp_path,
        monkeypatch,
        args=["--no-sessions", "--no-extract"],
        stdin="n\n",
    )
    assert r.exit_code == 0, r.output
    assert "Summarize chat sessions?" not in r.output
    assert "Embed chat sessions" not in r.output
