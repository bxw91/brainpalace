"""Tests for the dashboard self-lifecycle (launch/stop/status + runtime pidfile)."""

from __future__ import annotations

import os

import pytest

import brainpalace_dashboard.server as srv

#: The real ``list_dashboard_pids`` captured at import — the autouse fixture
#: below stubs the module attr to ``[]``, so the state-dir-scoping test calls
#: this saved reference to exercise the genuine /proc scan.
_REAL_LIST_DASHBOARD_PIDS = srv.list_dashboard_pids


@pytest.fixture(autouse=True)
def _no_stray_dashboards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: the process table has no dashboard procs, so the reaper is a
    no-op. Tests that exercise reaping override ``list_dashboard_pids`` locally.
    """
    monkeypatch.setattr(srv, "list_dashboard_pids", lambda: [])


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


def test_ensure_running_returns_existing_without_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A healthy dashboard is reported as-is — no relaunch, started=False."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(
        srv,
        "dashboard_status",
        lambda: {
            "status": "running",
            "pid": 7,
            "port": 8787,
            "base_url": "http://127.0.0.1:8787/dashboard/",
            "healthy": True,
        },
    )

    def _no_launch(*a, **k):
        raise AssertionError("launch_dashboard must not run when already up")

    monkeypatch.setattr(srv, "launch_dashboard", _no_launch)

    out = srv.ensure_running(open_browser_if_new=True)
    assert out["started"] is False
    assert out["base_url"] == "http://127.0.0.1:8787/dashboard/"


def test_ensure_running_launches_when_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """When down, ensure_running launches and forwards the browser flag."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(srv, "dashboard_status", lambda: {"status": "not_running"})
    seen: dict[str, object] = {}

    def _fake_launch(*, open_browser, foreground, timeout):
        seen["open_browser"] = open_browser
        srv.write_dashboard_runtime(
            {"pid": 1, "port": 8787, "base_url": "http://127.0.0.1:8787/dashboard/"}
        )
        return "http://127.0.0.1:8787/dashboard/"

    monkeypatch.setattr(srv, "launch_dashboard", _fake_launch)

    out = srv.ensure_running(open_browser_if_new=True)
    assert out["started"] is True
    assert out["base_url"] == "http://127.0.0.1:8787/dashboard/"
    assert seen["open_browser"] is True


class TestReapOrphanDashboards:
    """reap_orphan_dashboards SIGTERMs every dashboard except keep_pid."""

    def test_reaps_all_when_keep_none(self) -> None:
        killed: list[int] = []
        reaped = srv.reap_orphan_dashboards(
            keep_pid=None,
            kill_fn=killed.append,
            list_fn=lambda: [101, 102, 103],
        )
        assert killed == [101, 102, 103]
        assert reaped == [101, 102, 103]

    def test_keeps_the_tracked_pid(self) -> None:
        killed: list[int] = []
        reaped = srv.reap_orphan_dashboards(
            keep_pid=102,
            kill_fn=killed.append,
            list_fn=lambda: [101, 102, 103],
        )
        assert killed == [101, 103]
        assert 102 not in reaped

    def test_never_reaps_self(self) -> None:
        killed: list[int] = []
        reaped = srv.reap_orphan_dashboards(
            keep_pid=None,
            kill_fn=killed.append,
            list_fn=lambda: [os.getpid(), 200],
        )
        assert killed == [200]
        assert os.getpid() not in reaped

    def test_skips_dead_pid_without_raising(self) -> None:
        def boom(pid: int) -> None:
            raise ProcessLookupError

        reaped = srv.reap_orphan_dashboards(
            keep_pid=None, kill_fn=boom, list_fn=lambda: [404]
        )
        assert reaped == []


def test_launch_reaps_strays_before_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """With no healthy tracked dashboard, launch reaps orphans before spawning."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    killed: list[int] = []
    monkeypatch.setattr(srv, "list_dashboard_pids", lambda: [501, 502])
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: killed.append(pid))

    class FakeProc:
        pid = 600

    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(srv, "_port_free", lambda host, port: True)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=20: True)

    srv.launch_dashboard(open_browser=False)
    assert killed == [501, 502]


def test_stop_reaps_orphans_with_no_pidfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Even with a stale/absent pidfile, stop reaps live dashboard strays."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    killed: list[int] = []
    monkeypatch.setattr(srv, "list_dashboard_pids", lambda: [701, 702])
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: killed.append(pid))

    out = srv.stop_dashboard()
    assert killed == [701, 702]
    assert out["status"] == "stopped"
    assert out["reaped"] == [701, 702]


# --- regression coverage for the recurring two-dashboard / empty-list bug ----


def test_is_alive_false_for_zombie(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zombie (exited-but-unreaped) child must read as dead, not alive.

    Otherwise os.kill(pid, 0) reports the corpse alive and the singleton pidfile
    stays poisoned forever (self-heal never relaunches)."""
    monkeypatch.setattr(srv, "_proc_state", lambda pid: "Z")
    killed: list[int] = []
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: killed.append(pid))

    assert srv._is_alive(12345) is False
    assert killed == []  # short-circuits before the os.kill probe


def test_is_alive_true_for_running_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "_proc_state", lambda pid: "S")
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: None)
    assert srv._is_alive(1) is True


def test_ensure_running_relaunches_when_unhealthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A tracked-but-unhealthy dashboard (dead socket / zombie) is relaunched."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    srv.write_dashboard_runtime(
        {"pid": 9, "port": 8787, "base_url": "http://127.0.0.1:8787/dashboard/"}
    )
    monkeypatch.setattr(
        srv,
        "dashboard_status",
        lambda: {
            "status": "running",
            "pid": 9,
            "port": 8787,
            "base_url": "http://127.0.0.1:8787/dashboard/",
            "healthy": False,
        },
    )
    launched: list[int] = []

    def _fake_launch(*, open_browser, foreground, timeout):
        launched.append(1)
        srv.write_dashboard_runtime(
            {"pid": 10, "port": 8787, "base_url": "http://127.0.0.1:8787/dashboard/"}
        )
        return "http://127.0.0.1:8787/dashboard/"

    monkeypatch.setattr(srv, "launch_dashboard", _fake_launch)

    out = srv.ensure_running()
    assert launched == [1]  # relaunched despite status == "running"
    assert out["started"] is True


def test_launch_does_not_detach_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Under pytest, the spawned dashboard must not start a new session — a
    detached real daemon would outlive the test and leak on a climbed port."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "t_no_detach")
    seen: dict[str, object] = {}

    class FakeProc:
        pid = 777

    def _popen(cmd, **kwargs):
        seen.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(srv.subprocess, "Popen", _popen)
    monkeypatch.setattr(srv, "_port_free", lambda host, port: True)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=20: True)

    srv.launch_dashboard(open_browser=False)
    assert seen["start_new_session"] is False


def test_list_dashboard_pids_scoped_to_active_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Only dashboards sharing our XDG state dir are reapable; a process under a
    different XDG_STATE_HOME (e.g. another pytest run) is left alone."""
    import io

    state_home = tmp_path / "ours"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    marker = b"python\x00-m\x00uvicorn\x00brainpalace_dashboard.app\x00"
    files = {
        "/proc/101/cmdline": marker,
        "/proc/101/environ": f"XDG_STATE_HOME={state_home}\x00".encode(),
        "/proc/202/cmdline": marker,
        "/proc/202/environ": b"XDG_STATE_HOME=/tmp/some-other-run\x00",
    }

    def _fake_open(path, mode="r", *a, **k):
        key = str(path)
        if key in files:
            return io.BytesIO(files[key])
        raise FileNotFoundError(key)

    monkeypatch.setattr("builtins.open", _fake_open)
    monkeypatch.setattr(
        srv.glob, "glob", lambda pat: ["/proc/101/cmdline", "/proc/202/cmdline"]
    )

    assert _REAL_LIST_DASHBOARD_PIDS() == [101]
