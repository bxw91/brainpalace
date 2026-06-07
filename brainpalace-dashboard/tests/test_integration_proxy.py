import asyncio
import json

import pytest

pytestmark = pytest.mark.integration


def test_proxy_status_against_real_server(tmp_path, monkeypatch) -> None:
    """Start a real server, proxy GET /health/status, then stop it."""
    import brainpalace_dashboard.services.instances as inst_mod
    from brainpalace_dashboard.services.instances import InstanceService, instance_id
    from brainpalace_dashboard.services.proxy import ProxyService

    # Isolate ALL durable dashboard state (dashboard_known.json + the global
    # registry.json that launch_server's update_registry writes) under tmp so the
    # test never pollutes the developer's real ~/.local/state/brainpalace.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg_state"))

    root = tmp_path
    state = root / ".brainpalace"
    state.mkdir()
    # Real project config lives in config.json (matches brainpalace init's
    # DEFAULT_CONFIG). auto_port picks a free port so parallel runs don't collide.
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
    iid = instance_id(str(root))
    svc.start(iid)
    try:
        proxy = ProxyService()
        out = asyncio.run(proxy.request(iid, "GET", "/health/status"))
        # Confirmed live key on /health/status.
        assert "total_chunks" in out
    finally:
        svc.stop(iid)
