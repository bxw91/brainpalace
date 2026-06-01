"""Phase 6 — init --start validates providers before starting/indexing.

These tests mock the server-side validator so they assert the CLI *gating*
behaviour deterministically (independent of the machine's real provider keys /
.env): a critical provider error must abort init BEFORE any server start or
index job; otherwise init proceeds.
"""

from dataclasses import dataclass
from unittest.mock import patch

from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


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
