"""Tests for the dashboard self-lifecycle (launch/stop/status + runtime pidfile)."""

from __future__ import annotations

import pytest

import brainpalace_dashboard.server as srv


def test_launch_writes_runtime_and_returns_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    class FakeProc:
        pid = 555

    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(srv, "_port_free", lambda host, port: True)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=20: True)

    url = srv.launch_dashboard(open_browser=False)
    assert url == "http://127.0.0.1:8787/dashboard/"

    rt = srv.read_dashboard_runtime()
    assert rt is not None
    assert rt["pid"] == 555
    assert rt["port"] == 8787


def test_launch_scans_to_next_free_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    class FakeProc:
        pid = 42

    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: FakeProc())
    # 8787 busy, 8788 free.
    monkeypatch.setattr(srv, "_port_free", lambda host, port: port != 8787)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=20: True)

    url = srv.launch_dashboard(open_browser=False)
    assert url == "http://127.0.0.1:8788/dashboard/"


def test_stop_signals_pid(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    srv.write_dashboard_runtime(
        {
            "pid": 999,
            "port": 8787,
            "base_url": "http://127.0.0.1:8787/dashboard/",
        }
    )
    killed: dict[str, int] = {}
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: killed.update(pid=pid))
    monkeypatch.setattr(srv, "_is_alive", lambda pid: False)

    out = srv.stop_dashboard()
    assert killed["pid"] == 999
    assert out["status"] == "stopped"
    assert srv.read_dashboard_runtime() is None


def test_stop_when_not_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    out = srv.stop_dashboard()
    assert out["status"] == "not_running"


def test_status_reports_running_and_health(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    srv.write_dashboard_runtime(
        {
            "pid": 321,
            "port": 8787,
            "base_url": "http://127.0.0.1:8787/dashboard/",
        }
    )
    monkeypatch.setattr(srv, "_is_alive", lambda pid: True)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=2: True)

    out = srv.dashboard_status()
    assert out["status"] == "running"
    assert out["pid"] == 321
    assert out["healthy"] is True


def test_status_when_not_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    out = srv.dashboard_status()
    assert out["status"] == "not_running"
