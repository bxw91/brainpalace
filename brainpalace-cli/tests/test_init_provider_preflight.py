"""Phase 6 — init --start validates providers before starting/indexing.

These tests mock the server-side validator so they assert the CLI *gating*
behaviour deterministically (independent of the machine's real provider keys /
.env): a critical provider error must abort init BEFORE any server start or
index job; otherwise init proceeds.
"""

from dataclasses import dataclass
from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.commands.init import _provider_needs, init_command
from brainpalace_cli.commands.init_plan import InitPlan


@dataclass
class _FakeErr:
    message: str
    severity: str
    provider_type: str
    field: str = ""

    def __str__(self) -> str:
        return f"[CRITICAL] {self.provider_type}: {self.message}"


def _run(args, monkeypatch, tmp_path, *, errors, critical):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    # Patch the server validators that _preflight_providers imports lazily.
    pc = "brainpalace_server.config.provider_config"
    with (
        patch(f"{pc}.load_provider_settings", return_value=object()),
        patch(f"{pc}.clear_settings_cache"),
        patch(f"{pc}.validate_provider_config", return_value=errors),
        patch(f"{pc}.has_critical_errors", return_value=critical),
        patch("brainpalace_cli.commands.init._run_subcommand") as mock_run,
    ):
        mock_run.return_value = {"step": "start", "status": "ok"}
        result = CliRunner().invoke(init_command, args)
    return result, mock_run


def test_init_start_fails_fast_on_critical_provider_error(tmp_path, monkeypatch):
    err = _FakeErr(
        message="No API key found for anthropic summarization. "
        "Set ANTHROPIC_API_KEY environment variable.",
        severity="critical",
        provider_type="summarization",
    )
    result, mock_run = _run(
        ["--path", str(tmp_path), "--start"],
        monkeypatch,
        tmp_path,
        errors=[err],
        critical=True,
    )
    assert result.exit_code != 0
    assert "summarization" in result.output.lower()
    assert "ANTHROPIC_API_KEY" in result.output
    mock_run.assert_not_called()  # nothing started/indexed on bad config


def test_init_start_proceeds_when_providers_valid(tmp_path, monkeypatch):
    result, mock_run = _run(
        ["--path", str(tmp_path), "--start"],
        monkeypatch,
        tmp_path,
        errors=[],
        critical=False,
    )
    assert result.exit_code == 0, result.output
    mock_run.assert_called()  # preflight passed -> server start attempted


def test_init_without_start_skips_preflight(tmp_path, monkeypatch):
    # No --start: preflight must not run, init succeeds even if it would fail.
    result, mock_run = _run(
        ["--path", str(tmp_path)],
        monkeypatch,
        tmp_path,
        errors=[_FakeErr("x", "critical", "embedding")],
        critical=True,
    )
    assert result.exit_code == 0, result.output


def _plan(**kw) -> InitPlan:
    # EVERY InitPlan field is required (no dataclass defaults) — construct all
    # of them, including `billable` (verified 2026-07-06 at init_plan.py:31-38:
    # start, watch, sessions, archive, extract, git_history, confirm, billable).
    base = {
        "start": True,
        "watch": "off",
        "sessions": None,
        "archive": None,
        "extract": False,
        "git_history": False,
        "confirm": False,
        "billable": False,
    }
    base.update(kw)
    return InitPlan(**base)


def test_needs_nothing_for_pure_records_start():
    # watch off, no session embed, no git history -> no provider needed
    assert _provider_needs(_plan()) == (False, False)


def test_watch_auto_needs_both():
    assert _provider_needs(_plan(watch="auto")) == (True, True)


def test_folders_need_both():
    assert _provider_needs(_plan(), folders=("/x",)) == (True, True)


def test_session_embed_needs_embedding_only():
    assert _provider_needs(_plan(sessions=True)) == (True, False)


def test_git_history_needs_embedding_only():
    assert _provider_needs(_plan(git_history=True)) == (True, False)


def test_server_side_distill_needs_both():
    # persisted extraction.mode=auto/provider runs the SERVER distiller, which
    # uses BOTH the summarization provider and the embedder — even with watch
    # off. server_distill must force both needs on (hardening #1).
    assert _provider_needs(_plan(), server_distill=True) == (True, True)


def _run_needs(args, monkeypatch, tmp_path, *, errors):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    pc = "brainpalace_server.config.provider_config"
    crit = lambda errs: any(e.severity == "critical" for e in errs)  # noqa: E731
    with (
        patch(f"{pc}.load_provider_settings", return_value=object()),
        patch(f"{pc}.clear_settings_cache"),
        patch(f"{pc}.validate_provider_config", return_value=errors),
        patch(f"{pc}.has_critical_errors", side_effect=crit),
        patch("brainpalace_cli.commands.init._run_subcommand") as mock_run,
    ):
        mock_run.return_value = {"step": "start", "status": "ok"}
        result = CliRunner().invoke(init_command, args)
    return result, mock_run


def test_no_watch_start_downgrades_unneeded_provider_criticals(tmp_path, monkeypatch):
    errs = [
        _FakeErr(
            "Missing API key for openai embeddings. Set OPENAI_API_KEY "
            "environment variable.",
            "critical",
            "embedding",
        ),
        _FakeErr(
            "Missing API key for anthropic summarization. Set "
            "ANTHROPIC_API_KEY environment variable.",
            "critical",
            "summarization",
        ),
    ]
    # --no-watch --no-sessions --no-git-history => nothing will embed/summarize
    result, mock_run = _run_needs(
        [
            "--path",
            str(tmp_path),
            "--start",
            "--no-watch",
            "--no-sessions",
            "--no-git-history",
            "--yes",
        ],
        monkeypatch,
        tmp_path,
        errors=errs,
    )
    assert result.exit_code == 0, result.output
    mock_run.assert_called()  # server start went ahead
    assert "not needed yet" in result.output.lower()
    assert "OPENAI_API_KEY" in result.output  # note still names the env var


def test_watch_auto_still_fails_fast_on_missing_embedding(tmp_path, monkeypatch):
    errs = [
        _FakeErr(
            "Missing API key for openai embeddings. Set OPENAI_API_KEY "
            "environment variable.",
            "critical",
            "embedding",
        ),
    ]
    result, mock_run = _run_needs(
        ["--path", str(tmp_path), "--start", "--yes"],  # default watch=auto
        monkeypatch,
        tmp_path,
        errors=errs,
    )
    assert result.exit_code != 0
    assert "OPENAI_API_KEY" in result.output
    mock_run.assert_not_called()


def test_deferred_provider_surfaces_in_json(tmp_path, monkeypatch):
    # hardening #4: a deferred (un-needed) critical must still reach --json
    # consumers as a `deferred_providers` entry naming the env var.
    errs = [
        _FakeErr(
            "Missing API key for openai embeddings. Set OPENAI_API_KEY "
            "environment variable.",
            "critical",
            "embedding",
        ),
    ]
    result, mock_run = _run_needs(
        [
            "--path",
            str(tmp_path),
            "--start",
            "--no-watch",
            "--no-sessions",
            "--no-git-history",
            "--yes",
            "--json",
        ],
        monkeypatch,
        tmp_path,
        errors=errs,
    )
    assert result.exit_code == 0, result.output
    assert "deferred_providers" in result.output
    assert "OPENAI_API_KEY" in result.output
    mock_run.assert_called()


def test_server_distill_config_still_blocks_missing_summarization(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.read_session_state",
        lambda _sd: ("auto", True),
    )
    errs = [
        _FakeErr(
            "Missing API key for anthropic summarization. Set "
            "ANTHROPIC_API_KEY environment variable.",
            "critical",
            "summarization",
        ),
    ]
    result, mock_run = _run_needs(
        [
            "--path",
            str(tmp_path),
            "--start",
            "--no-watch",
            "--no-sessions",
            "--no-git-history",
            "--yes",
        ],
        monkeypatch,
        tmp_path,
        errors=errs,
    )
    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output
    mock_run.assert_not_called()
