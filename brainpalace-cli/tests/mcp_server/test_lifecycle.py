"""Unit tests for ``brainpalace_cli.mcp.lifecycle.ensure_http_server``.

The orchestrator's branches — server-already-live, uninitialised
project, start-failure swallowed — are exercised by patching the
discovery helpers and the inner :func:`_start_for` so no actual server
process is spawned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from brainpalace_cli.mcp_server import lifecycle


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project: Path | None,
    url: str | None,
    start_side_effect: Exception | None = None,
) -> dict[str, Any]:
    """Patch lifecycle's three external touch-points and return a spy dict."""
    calls: dict[str, Any] = {"start_for": 0, "start_for_args": None}

    monkeypatch.setattr(lifecycle, "discover_project_dir", lambda start=None: project)
    monkeypatch.setattr(lifecycle, "discover_server_url", lambda start=None: url)

    def fake_start_for(project_root: Path, timeout: int) -> None:
        calls["start_for"] += 1
        calls["start_for_args"] = (project_root, timeout)
        if start_side_effect is not None:
            raise start_side_effect

    monkeypatch.setattr(lifecycle, "_start_for", fake_start_for)
    return calls


def test_ensure_noop_when_server_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery returns a URL → already healthy → no spawn."""
    calls = _patch(monkeypatch, project=Path("/p/demo"), url="http://127.0.0.1:9000")

    lifecycle.ensure_http_server()

    assert calls["start_for"] == 0


def test_ensure_starts_when_no_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project exists but no live server → _start_for called once."""
    calls = _patch(monkeypatch, project=Path("/p/demo"), url=None)

    lifecycle.ensure_http_server()

    assert calls["start_for"] == 1
    project_root, timeout = calls["start_for_args"]
    assert project_root == Path("/p/demo")
    assert timeout == 60  # default


def test_ensure_skips_uninitialised(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``.brainpalace/`` → ``discover_project_dir`` returns None → no spawn."""
    calls = _patch(monkeypatch, project=None, url=None)

    lifecycle.ensure_http_server()

    assert calls["start_for"] == 0


def test_ensure_swallows_start_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``_start_for`` raises → caught, logged to stderr, function returns."""
    boom = RuntimeError("uvicorn died on boot")
    _patch(monkeypatch, project=Path("/p/demo"), url=None, start_side_effect=boom)

    # Must not raise — that would hang the MCP handshake in production.
    lifecycle.ensure_http_server()

    captured = capsys.readouterr()
    assert (
        captured.out == ""
    ), "ensure_http_server must keep stdout silent (MCP transport)"
    assert "uvicorn died on boot" in captured.err
    assert "--ensure-server failed" in captured.err


def test_ensure_honours_timeout_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller can pass a custom timeout."""
    calls = _patch(monkeypatch, project=Path("/p/demo"), url=None)

    lifecycle.ensure_http_server(timeout=15)

    _, timeout = calls["start_for_args"]
    assert timeout == 15
