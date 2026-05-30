"""Tests for the whoami command (B10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.whoami import whoami_command


def test_whoami_no_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """No owning project → exit 1, found=false."""
    monkeypatch.setattr(
        "brainpalace_cli.commands.whoami.discover_project_dir",
        lambda start=None: None,
    )
    result = CliRunner().invoke(whoami_command, ["--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["found"] is False


def test_whoami_project_and_live_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project found with a live server → exit 0, url reported."""
    monkeypatch.setattr(
        "brainpalace_cli.commands.whoami.discover_project_dir",
        lambda start=None: Path("/p/demo"),
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.whoami.discover_server_url",
        lambda start=None: "http://127.0.0.1:8000",
    )
    result = CliRunner().invoke(whoami_command, ["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["project_root"] == "/p/demo"
    assert data["url"] == "http://127.0.0.1:8000"
    assert data["server"] == "running"


def test_whoami_project_server_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Project found but server not running → exit 2."""
    monkeypatch.setattr(
        "brainpalace_cli.commands.whoami.discover_project_dir",
        lambda start=None: Path("/p/demo"),
    )
    monkeypatch.setattr(
        "brainpalace_cli.commands.whoami.discover_server_url",
        lambda start=None: None,
    )
    result = CliRunner().invoke(whoami_command, ["--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["server"] == "down"
