"""Tests for the reset command -- Task 11: --include-sessions flag."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from click.testing import CliRunner

from brainpalace_cli.commands.reset import reset_command


def _make_client_mock() -> MagicMock:
    """Return a DocServeClient mock that works as a context manager."""
    mock_response = SimpleNamespace(job_id="j", status="ok", message="done")
    mock_client = MagicMock()
    mock_client.reset.return_value = mock_response

    mock_ctx_mgr = MagicMock()
    mock_ctx_mgr.__enter__ = MagicMock(return_value=mock_client)
    mock_ctx_mgr.__exit__ = MagicMock(return_value=False)

    mock_cls = MagicMock(return_value=mock_ctx_mgr)
    return mock_cls


# ---------------------------------------------------------------------------
# Flag existence
# ---------------------------------------------------------------------------


def test_reset_has_include_sessions_flag() -> None:
    result = CliRunner().invoke(reset_command, ["--help"])
    assert result.exit_code == 0
    assert "--include-sessions" in result.output


# ---------------------------------------------------------------------------
# Archive preservation / deletion
# ---------------------------------------------------------------------------


def test_reset_preserves_archive_by_default(tmp_path, monkeypatch) -> None:
    state = tmp_path / ".brainpalace"
    arch = state / "session_archive"
    arch.mkdir(parents=True)
    (arch / "2026-06-01").mkdir()

    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.get_state_dir", lambda *a, **k: state
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.DocServeClient", _make_client_mock()
    )

    result = CliRunner().invoke(reset_command, ["--yes"])
    assert result.exit_code == 0, result.output
    assert arch.exists()  # preserved


def test_reset_include_sessions_deletes_archive(tmp_path, monkeypatch) -> None:
    state = tmp_path / ".brainpalace"
    arch = state / "session_archive"
    arch.mkdir(parents=True)
    (arch / "2026-06-01").mkdir()

    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.get_state_dir", lambda *a, **k: state
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.DocServeClient", _make_client_mock()
    )

    result = CliRunner().invoke(reset_command, ["--yes", "--include-sessions"])
    assert result.exit_code == 0, result.output
    assert not arch.exists()  # deleted


def test_reset_include_sessions_no_archive_is_graceful(tmp_path, monkeypatch) -> None:
    """--include-sessions is a no-op when no archive directory exists."""
    state = tmp_path / ".brainpalace"
    state.mkdir(parents=True)
    # No session_archive subdirectory created.

    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.get_state_dir", lambda *a, **k: state
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.DocServeClient", _make_client_mock()
    )

    result = CliRunner().invoke(reset_command, ["--yes", "--include-sessions"])
    assert result.exit_code == 0, result.output


def test_reset_abort_does_not_delete_archive(tmp_path, monkeypatch) -> None:
    """Aborting at the confirmation prompt must leave the archive intact."""
    state = tmp_path / ".brainpalace"
    arch = state / "session_archive"
    arch.mkdir(parents=True)

    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.get_state_dir", lambda *a, **k: state
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.reset.DocServeClient", _make_client_mock()
    )

    # Provide "n" to the confirmation prompt (no --yes flag).
    result = CliRunner().invoke(reset_command, ["--include-sessions"], input="n\n")
    assert result.exit_code == 0, result.output
    assert arch.exists()  # must NOT have been deleted on abort
