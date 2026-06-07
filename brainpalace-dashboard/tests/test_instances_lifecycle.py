from pathlib import Path

import brainpalace_dashboard.services.instances as inst_mod
from brainpalace_dashboard.services.instances import InstanceService, instance_id


def _patch_registry(monkeypatch, root, state_dir) -> None:
    monkeypatch.setattr(
        inst_mod,
        "get_registry",
        lambda: {root: {"state_dir": str(state_dir), "project_name": "foo"}},
    )


def test_start_invokes_launch_server(monkeypatch, tmp_path) -> None:
    root = str(tmp_path)
    state = tmp_path / ".brainpalace"
    state.mkdir()
    _patch_registry(monkeypatch, root, state)
    seen = {}
    monkeypatch.setattr(
        inst_mod,
        "launch_server",
        lambda **kw: seen.update(kw)
        or {"pid": 99, "base_url": "http://127.0.0.1:8005"},
    )
    svc = InstanceService()
    out = svc.start(instance_id(root))
    assert out["pid"] == 99
    assert seen["project_root"] == Path(root)


def test_stop_signals_pid_and_deregisters(monkeypatch, tmp_path) -> None:
    root = str(tmp_path)
    state = tmp_path / ".brainpalace"
    state.mkdir()
    _patch_registry(monkeypatch, root, state)
    monkeypatch.setattr(inst_mod, "read_runtime", lambda sd: {"pid": 1234})
    killed: dict = {}
    monkeypatch.setattr(
        inst_mod.os, "kill", lambda pid, sig: killed.update(pid=pid, sig=sig)
    )
    # Process is alive until SIGTERM is sent, then reported dead — exercises the
    # reaping wait loop without spawning a real process.
    monkeypatch.setattr(inst_mod, "is_process_alive", lambda pid: "pid" not in killed)
    monkeypatch.setattr(inst_mod, "_reap_if_child", lambda pid: None)
    monkeypatch.setattr(
        inst_mod, "remove_from_registry", lambda root: killed.update(dereg=True)
    )
    monkeypatch.setattr(inst_mod, "delete_runtime", lambda sd: None)
    svc = InstanceService()
    out = svc.stop(instance_id(root))
    assert killed["pid"] == 1234
    assert killed["sig"] == inst_mod.signal.SIGTERM
    assert killed["dereg"] is True
    assert out["status"] == "stopped"
