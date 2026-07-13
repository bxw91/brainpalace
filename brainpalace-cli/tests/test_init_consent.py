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
    # Consent fields are drilled from the grid by NUMBER (never plain-walked).
    # Archiving (the free COPY) is its own division (11); Chat Session : Vector
    # Indexing (the billable embed) is division 12. Drill 12 → Vector enabled=Y (fires
    # the embed consent), include-user-turns=N, Enter past the 5 remaining session
    # fields → [C]ontinue, estimate?=N, proceed=N → config-only.
    # (Chat Session : Summarization's legacy `mode` is grid-hidden — superseded by the
    # Extraction Engine's extraction.mode — so it is not drilled here.)
    r = _invoke(
        tmp_path,
        monkeypatch,
        args=[],
        # Index-target picker first (folder=., type=both), then the grid drill.
        stdin=".\nboth\n12\ny\nn\n\n\n\n\n\nc\nn\nn\n",
    )
    assert r.exit_code == 0, r.output
    # The consent warning appears when the division is drilled.
    assert "embedding chat transcripts is billable" in r.output  # session_indexing
    # the embed consent names the resolved provider/model
    assert "openai text-embedding-3-large" in r.output
    # Declined the Proceed gate → config-only: the "next steps" hint to start the
    # server manually is shown (the server was not auto-started).
    assert "brainpalace start" in r.output


def test_estimate_gate_precedes_final_proceed_on_fresh_start(tmp_path, monkeypatch):
    # #3: a fresh interactive run asks "Estimate token usage first?" BEFORE the
    # final "init will:" / start gate. Skip the estimate (n), then accept (y) →
    # the start pipeline runs. With no --start/--no-start flag, the final gate is
    # the explicit "Start the BrainPalace server now?" question.
    monkeypatch.setattr(initmod, "_start_and_watch", lambda **k: [])
    # graphrag-extract=N, reranker-change=N, lemma=N, review=[C]ontinue,
    # estimate?=N, start=Y
    # (archive/sessions/extract/git-history suppressed with flags)
    # Review now fires BEFORE estimate (#12): c accepts review, then n skips
    # estimate, then y starts the server.
    r = _invoke(
        tmp_path,
        monkeypatch,
        args=["--no-sessions", "--no-extract", "--no-git-history", "--no-archive"],
        # picker(folder=.,type=both), graphrag=N, reranker=N, lemma=N, review=C,
        # estimate?=N, start=Y
        stdin=".\nboth\nn\nn\nn\nc\nn\ny\n",
    )
    assert r.exit_code == 0, r.output
    gate = r.output.find("Estimate token usage first?")
    start = r.output.find("Start the BrainPalace server now?")
    assert gate != -1, r.output
    assert start != -1, r.output
    assert gate < start  # estimate gate comes before the final start question
    assert "init will:" in r.output


def test_explicit_flags_skip_prompts(tmp_path, monkeypatch):
    # All capabilities set by flag → no per-feature prompts; just the reranker
    # gate (N = keep inherited), lemma (N), review=[C]ontinue, estimate gate
    # (N = skip), then the final proceed confirm (N).
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
        # picker(folder=.,type=both); then
        # reranker=N, lemma=N, review=C, estimate?=N, proceed=N
        stdin=".\nboth\nn\nn\nc\nn\nn\n",
    )
    assert r.exit_code == 0, r.output
    assert "Summarize chat sessions?" not in r.output
    assert "Embed chat sessions" not in r.output
    assert "Index git commit history?" not in r.output
