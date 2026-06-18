import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import brainpalace_server.self_heal as sh


def _install_fake_dashboard(monkeypatch, tmp_path, *, status, autostart=True):
    """Inject fake `brainpalace_dashboard` modules (the package isn't installed in
    the server env) so `_heal_dashboard` exercises its real debounce logic against
    a stubbed `dashboard_status`/`ensure_running`. Returns the fake server module
    (its `ensure_running` is a MagicMock to assert relaunch calls)."""
    dash = types.ModuleType("brainpalace_dashboard.server")
    dash.read_dashboard_runtime = lambda: {"pid": -1}  # no live child to waitpid
    dash.dashboard_status = lambda: status
    dash.ensure_running = MagicMock()
    pkg = types.ModuleType("brainpalace_dashboard")
    pkg.server = dash
    cfg = types.ModuleType("brainpalace_dashboard.config")
    cfg.load_dashboard_config = lambda: SimpleNamespace(autostart=autostart)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard", pkg)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard.server", dash)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard.config", cfg)
    # Lock under tmp so the real file_lock works without touching XDG state.
    monkeypatch.setattr(
        "brainpalace_server.registry.get_xdg_state_dir", lambda: tmp_path
    )
    return dash


def test_heal_dashboard_healthy_no_relaunch(monkeypatch, tmp_path):
    dash = _install_fake_dashboard(
        monkeypatch, tmp_path, status={"status": "running", "healthy": True}
    )
    healer = sh.HealState()
    healer.dashboard_unhealthy_strikes = 2  # prior strikes must reset on healthy
    sh._heal_dashboard(healer)
    dash.ensure_running.assert_not_called()
    assert healer.dashboard_unhealthy_strikes == 0


def test_heal_dashboard_debounces_transient_unhealthy(monkeypatch, tmp_path):
    """A live-but-unhealthy dashboard is NOT relaunched until it fails
    DASHBOARD_UNHEALTHY_STRIKES consecutive heartbeats (no single-probe flap)."""
    dash = _install_fake_dashboard(
        monkeypatch, tmp_path, status={"status": "running", "healthy": False}
    )
    healer = sh.HealState()
    for _ in range(sh.DASHBOARD_UNHEALTHY_STRIKES - 1):
        sh._heal_dashboard(healer)
        dash.ensure_running.assert_not_called()
    assert healer.dashboard_unhealthy_strikes == sh.DASHBOARD_UNHEALTHY_STRIKES - 1
    # The strike that hits the budget triggers the relaunch and resets the count.
    sh._heal_dashboard(healer)
    dash.ensure_running.assert_called_once_with(open_browser_if_new=False)
    assert healer.dashboard_unhealthy_strikes == 0


def test_heal_dashboard_relaunches_immediately_when_down(monkeypatch, tmp_path):
    """A truly dead dashboard (pid gone -> not_running) is relaunched at once,
    with no strike debounce."""
    dash = _install_fake_dashboard(
        monkeypatch, tmp_path, status={"status": "not_running"}
    )
    healer = sh.HealState()
    sh._heal_dashboard(healer)
    dash.ensure_running.assert_called_once_with(open_browser_if_new=False)


@pytest.mark.asyncio
async def test_heal_once_restarts_dead_watcher_and_worker(monkeypatch):
    # watcher: 1 dead task, 1 auto folder expected -> heal (stop+start)
    watcher = MagicMock()
    watcher.dead_task_count.return_value = 1
    watcher.expected_auto_folder_count = AsyncMock(return_value=1)
    watcher.watched_folder_count = 1
    watcher.stop = AsyncMock()
    watcher.start = AsyncMock()

    # worker: not running -> restart
    worker = MagicMock()
    worker.is_running.return_value = False
    worker.start = AsyncMock()

    vector = MagicMock()
    vector.heal_if_corrupt = AsyncMock(return_value=0)

    app = SimpleNamespace(
        state=SimpleNamespace(
            file_watcher_service=watcher,
            job_worker=worker,
            vector_store=vector,
            state_dir=None,
            project_root="",
        )
    )

    healer = sh.HealState()
    await sh.heal_once(app, healer)

    watcher.stop.assert_awaited_once()
    watcher.start.assert_awaited_once()
    worker.start.assert_awaited_once()
    vector.heal_if_corrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_heal_index_heals_both_code_and_memory_stores():
    """The heartbeat recompacts the memory shadow index too, not just code."""
    code = MagicMock()
    code.heal_if_corrupt = AsyncMock(return_value=0)
    mem = MagicMock()
    mem.heal_if_corrupt = AsyncMock(return_value=0)

    app = SimpleNamespace(
        state=SimpleNamespace(vector_store=code, mem_vector_store=mem)
    )
    await sh._heal_index(app)

    code.heal_if_corrupt.assert_awaited_once()
    mem.heal_if_corrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_restart_capped(monkeypatch):
    worker = MagicMock()
    worker.is_running.return_value = False
    worker.start = AsyncMock()
    app = SimpleNamespace(
        state=SimpleNamespace(
            file_watcher_service=None,
            job_worker=worker,
            vector_store=None,
            state_dir=None,
            project_root="",
        )
    )
    healer = sh.HealState()
    for _ in range(sh.MAX_WORKER_RESTARTS + 3):
        await sh.heal_once(app, healer)
    assert worker.start.await_count == sh.MAX_WORKER_RESTARTS
