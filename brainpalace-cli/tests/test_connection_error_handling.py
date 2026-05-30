"""Tests for the centralised connection-error exit helper (E1)."""

from __future__ import annotations

import json

import pytest

from brainpalace_cli.client import (
    EXIT_CODE_CONNECTION_ERROR,
    ConnectionError,
    exit_on_connection_error,
)


def test_exit_code_is_7(capsys: pytest.CaptureFixture[str]) -> None:
    exc = ConnectionError("boom")
    with pytest.raises(SystemExit) as excinfo:
        exit_on_connection_error(exc, base_url="http://127.0.0.1:8000")
    assert excinfo.value.code == EXIT_CODE_CONNECTION_ERROR
    assert EXIT_CODE_CONNECTION_ERROR == 7


def test_canonical_message_written_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = ConnectionError("Unable to connect to http://x")
    with pytest.raises(SystemExit):
        exit_on_connection_error(exc, base_url="http://127.0.0.1:8000")

    captured = capsys.readouterr()
    assert "BrainPalace server not running" in captured.err
    assert "brainpalace start" in captured.err
    assert "http://127.0.0.1:8000" in captured.err
    # Stdout must remain clean for json_output=False
    assert captured.out == ""


def test_message_omits_url_when_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = ConnectionError("no url known")
    with pytest.raises(SystemExit):
        exit_on_connection_error(exc, base_url=None)

    err = capsys.readouterr().err
    # Canonical sentence still present but without " at <url>"
    assert "BrainPalace server not running" in err
    assert " at " not in err.split("\n")[0]


def test_json_mode_emits_structured_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = ConnectionError("connection refused")
    with pytest.raises(SystemExit):
        exit_on_connection_error(
            exc, base_url="http://127.0.0.1:8000", json_output=True
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    # First line of stderr is a single JSON object
    payload = json.loads(captured.err.strip())
    assert payload["error"] == "connection_error"
    assert payload["url"] == "http://127.0.0.1:8000"
    assert "BrainPalace server not running" in payload["message"]
    assert "connection refused" in payload["detail"]


def test_helper_is_no_return_in_practice() -> None:
    """Helper must always raise; no fall-through."""
    exc = ConnectionError("x")
    with pytest.raises(SystemExit):
        exit_on_connection_error(exc, base_url="http://x")
