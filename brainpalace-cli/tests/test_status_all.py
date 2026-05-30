"""Tests for `brainpalace status --all` (B2b)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.status import status_command


class _FakeClient:
    """Context-manager stand-in for DocServeClient."""

    def __init__(self, base_url: str, **kwargs: Any) -> None:
        self.base_url = base_url

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def health(self) -> SimpleNamespace:
        return SimpleNamespace(status="healthy", version="9.6.0", message=None)

    def status(self) -> SimpleNamespace:
        return SimpleNamespace(
            total_documents=10,
            total_chunks=42,
            file_watcher={"running": True, "watched_folders": 2},
            last_indexed_at="2026-05-20T00:00:00Z",
        )


def _two_instances() -> list[dict[str, Any]]:
    """One running, one stale — the stale one must be filtered out."""
    return [
        {
            "status": "running",
            "base_url": "http://127.0.0.1:8001",
            "project_root": "/p/one",
            "pid": 111,
            "project_name": "one",
        },
        {
            "status": "stale",
            "base_url": "http://127.0.0.1:8002",
            "project_root": "/p/two",
            "pid": 0,
            "project_name": "two",
        },
    ]


def _no_instances() -> list[dict[str, Any]]:
    return []


def test_status_all_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--all --json` emits an array of only the running servers."""
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.scan_instances", _two_instances
    )
    monkeypatch.setattr("brainpalace_cli.commands.status.DocServeClient", _FakeClient)
    result = CliRunner().invoke(status_command, ["--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total"] == 1  # the stale instance is excluded
    srv = data["servers"][0]
    assert srv["project_root"] == "/p/one"
    assert srv["total_chunks"] == 42
    assert srv["watcher_running"] is True


def test_status_all_no_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--all` with no running servers prints a message and exits 0."""
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.scan_instances", _no_instances
    )
    result = CliRunner().invoke(status_command, ["--all"])
    assert result.exit_code == 0
    assert "No running BrainPalace servers" in result.output
