import json

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_start_then_stop_real_server(tmp_path, monkeypatch) -> None:
    """Init a throwaway project, start via service, hit /health/, stop."""
    import brainpalace_dashboard.services.instances as inst_mod
    from brainpalace_dashboard.services.instances import InstanceService, instance_id

    # Isolate ALL durable dashboard state (dashboard_known.json + the global
    # registry.json that launch_server's update_registry writes) under tmp so the
    # test never pollutes the developer's real ~/.local/state/brainpalace.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))

    root = tmp_path
    state = root / ".brainpalace"
    state.mkdir()
    # Real project config lives in config.json (bind_host/auto_port/port_range_*),
    # matching brainpalace init's DEFAULT_CONFIG. auto_port picks a free port so
    # parallel runs don't collide. No provider config (config.yaml) is needed for
    # the server to boot and answer GET /health/.
    (state / "config.json").write_text(
        json.dumps(
            {
                "bind_host": "127.0.0.1",
                "auto_port": True,
                "port_range_start": 8600,
                "port_range_end": 8699,
            }
        )
    )
    monkeypatch.setattr(
        inst_mod,
        "get_registry",
        lambda: {str(root): {"state_dir": str(state), "project_name": "itest"}},
    )

    svc = InstanceService()
    rt = svc.start(instance_id(str(root)))
    try:
        base = rt["base_url"]
        r = httpx.get(f"{base}/health/", timeout=5)
        assert r.status_code == 200
    finally:
        out = svc.stop(instance_id(str(root)))
        assert out["status"] == "stopped"
