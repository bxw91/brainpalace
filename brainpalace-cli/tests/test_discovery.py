"""Tests for CWD-based server discovery (B1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from brainpalace_cli import discovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, status_code: int, json_data: dict[str, Any] | None = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict[str, Any]:
        return self._json


def _make_project(
    home: Path, name: str = "proj", runtime: dict[str, Any] | None = None
) -> Path:
    """Create an *initialized* ``home/name/.brainpalace/`` project.

    Always writes a ``config.yaml`` marker so the dir counts as a real project
    root (discovery skips bare scaffolds). Optionally also writes runtime.json.
    """
    proj = home / name
    ab = proj / ".brainpalace"
    ab.mkdir(parents=True)
    (ab / "config.yaml").write_text("api: {}\n")
    if runtime is not None:
        (ab / "runtime.json").write_text(json.dumps(runtime))
    return proj


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    health_status: int = 200,
    runtime_status: int = 200,
    runtime_json: dict[str, Any] | None = None,
) -> None:
    """Patch discovery.httpx.get to route /health/ and /runtime/ responses."""

    def _get(url: str, timeout: float | None = None) -> _FakeResp:
        if url.endswith("/health/"):
            return _FakeResp(health_status)
        if url.endswith("/runtime/"):
            return _FakeResp(runtime_status, runtime_json)
        return _FakeResp(404)

    monkeypatch.setattr("brainpalace_cli.discovery.httpx.get", _get)


def _patch_pid_alive(monkeypatch: pytest.MonkeyPatch, alive: bool = True) -> None:
    """Patch discovery.os.kill to simulate a live or dead PID."""

    def _kill(pid: int, sig: int) -> None:
        if not alive:
            raise ProcessLookupError

    monkeypatch.setattr("brainpalace_cli.discovery.os.kill", _kill)


# ---------------------------------------------------------------------------
# discover_project_dir
# ---------------------------------------------------------------------------


def test_finds_project_at_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .brainpalace/ at the start directory is found."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path)
    assert discovery.discover_project_dir(proj) == proj.resolve()


def test_walks_up_from_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery walks up from a deep subdirectory to the project root."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path)
    deep = proj / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert discovery.discover_project_dir(deep) == proj.resolve()


def test_no_project_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No .brainpalace/ anywhere up to $HOME returns None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sub = tmp_path / "x" / "y"
    sub.mkdir(parents=True)
    assert discovery.discover_project_dir(sub) is None


def test_outside_home_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A start directory outside $HOME is refused."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert discovery.discover_project_dir(outside) is None


def test_innermost_project_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nested projects, the innermost .brainpalace/ is returned."""
    monkeypatch.setenv("HOME", str(tmp_path))
    outer = _make_project(tmp_path, "outer")
    inner = _make_project(outer, "inner")
    deep = inner / "deep"
    deep.mkdir()
    assert discovery.discover_project_dir(deep) == inner.resolve()


# ---------------------------------------------------------------------------
# discover_server_url
# ---------------------------------------------------------------------------

_URL = "http://127.0.0.1:8000"


def test_server_url_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid runtime.json + live PID + healthy server + matching /runtime/."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL, "pid": 12345})
    _patch_pid_alive(monkeypatch, alive=True)
    _patch_http(monkeypatch, runtime_json={"project_root": str(proj)})
    assert discovery.discover_server_url(proj) == _URL


def test_server_url_runtime_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project without runtime.json yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path)  # no runtime.json
    assert discovery.discover_server_url(proj) is None


def test_server_url_runtime_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed runtime.json yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path)
    (proj / ".brainpalace" / "runtime.json").write_text("{not json")
    assert discovery.discover_server_url(proj) is None


def test_server_url_missing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """runtime.json without base_url/pid yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL})  # no pid
    assert discovery.discover_server_url(proj) is None


def test_server_url_pid_dead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead PID yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL, "pid": 12345})
    _patch_pid_alive(monkeypatch, alive=False)
    assert discovery.discover_server_url(proj) is None


def test_server_url_health_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-200 /health/ response yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL, "pid": 12345})
    _patch_pid_alive(monkeypatch, alive=True)
    _patch_http(monkeypatch, health_status=500)
    assert discovery.discover_server_url(proj) is None


def test_server_url_project_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A /runtime/ project_root for a different project yields None."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL, "pid": 12345})
    _patch_pid_alive(monkeypatch, alive=True)
    _patch_http(monkeypatch, runtime_json={"project_root": "/some/other/project"})
    assert discovery.discover_server_url(proj) is None


def test_server_url_runtime_endpoint_absent_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older server without /runtime/ (404) still resolves via health alone."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = _make_project(tmp_path, runtime={"base_url": _URL, "pid": 12345})
    _patch_pid_alive(monkeypatch, alive=True)
    _patch_http(monkeypatch, runtime_status=404)
    assert discovery.discover_server_url(proj) == _URL
