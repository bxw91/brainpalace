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
    # summarize=Y, embed=N, archive=Y, git-history=N, graphrag-extract=N,
    # reranker-change=N, lemma=N, compute=Y, estimate?=N, proceed=N
    # → config-only. The estimate now runs BEFORE the final Proceed (#3), so skip
    # it then decline.
    r = _invoke(tmp_path, monkeypatch, args=[], stdin="y\nn\ny\nn\nn\nn\nn\ny\nn\nn\n")
    assert r.exit_code == 0, r.output
    assert "Summarize chat sessions?" in r.output
    assert "Embed chat sessions" in r.output
    assert "Index git commit history?" in r.output
    # the embed prompt names the resolved provider
    assert "OpenAI text-embedding-3-large" in r.output


def test_estimate_gate_precedes_final_proceed_on_fresh_start(tmp_path, monkeypatch):
    # #3: a fresh interactive run asks "Estimate token usage first?" BEFORE the
    # final "init will:" / "Proceed?" gate. Skip the estimate (n), then proceed
    # (y) → the start pipeline runs.
    monkeypatch.setattr(initmod, "_start_and_watch", lambda **k: [])
    # graphrag-extract=N, reranker-change=N, lemma=N, compute=Y, estimate?=N, proceed=Y
    # (archive/sessions/extract/git-history suppressed with flags)
    r = _invoke(
        tmp_path,
        monkeypatch,
        args=["--no-sessions", "--no-extract", "--no-git-history", "--no-archive"],
        stdin="n\nn\nn\ny\nn\ny\n",
    )
    assert r.exit_code == 0, r.output
    gate = r.output.find("Estimate token usage first?")
    proceed = r.output.find("Proceed?")
    assert gate != -1, r.output
    assert proceed != -1, r.output
    assert gate < proceed  # estimate gate comes before the final Proceed
    assert "init will:" in r.output


def test_explicit_flags_skip_prompts(tmp_path, monkeypatch):
    # All capabilities set by flag → no per-feature prompts; just the reranker
    # gate (N = keep inherited), lemma (N), compute (Y), estimate gate (N = skip),
    # then the final proceed confirm (N).
    r = _invoke(
        tmp_path,
        monkeypatch,
        args=[
            "--no-sessions",
            "--no-extract",
            "--no-git-history",
            "--no-graphrag-extract",
            "--no-archive",
        ],
        stdin="n\nn\ny\nn\nn\n",
    )
    assert r.exit_code == 0, r.output
    assert "Summarize chat sessions?" not in r.output
    assert "Embed chat sessions" not in r.output
    assert "Index git commit history?" not in r.output
