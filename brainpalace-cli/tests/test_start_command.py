"""Start-time server reuse: honour the global registry, not just runtime.json."""

from click.testing import CliRunner

from brainpalace_cli.commands import start as start_mod
from brainpalace_cli.commands.start import start_command
from brainpalace_cli.xdg_paths import get_xdg_config_dir


def test_read_bind_inherits_global_bind(monkeypatch, tmp_path):
    """A bind key the project omits is inherited from the global XDG config.yaml."""
    import yaml

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    gdir = get_xdg_config_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "config.yaml").write_text(
        yaml.dump({"bind": {"bind_host": "0.0.0.0", "port_range_start": 9000}})
    )
    state = tmp_path / "proj" / ".brainpalace"
    state.mkdir(parents=True)
    (state / "config.yaml").write_text(yaml.dump({"bind": {"port_range_start": 7000}}))

    merged = start_mod.read_bind(state)
    assert merged["bind_host"] == "0.0.0.0"  # inherited from the global layer
    assert merged["port_range_start"] == 7000  # project overrides global


def test_read_bind_without_global_is_project_only(monkeypatch, tmp_path):
    import yaml

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    state = tmp_path / ".brainpalace"
    state.mkdir(parents=True)
    (state / "config.yaml").write_text(yaml.dump({"bind": {"bind_host": "1.2.3.4"}}))
    result = start_mod.read_bind(state)
    assert result["bind_host"] == "1.2.3.4"
    # remaining keys get code defaults
    assert result["port_range_start"] == 8000


def test_start_reuses_live_registry_server_for_same_project(monkeypatch, tmp_path):
    """If the registry already has a live, healthy server for this project_root,
    find_reusable_server returns its URL (so start reuses it instead of spawning
    a duplicate on a climbed port)."""
    project = tmp_path
    (project / ".brainpalace").mkdir()
    registry = {str(project): {"pid": 4242, "base_url": "http://127.0.0.1:8000"}}
    monkeypatch.setattr(start_mod, "is_process_alive", lambda _pid: True)
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.get_registry", lambda: registry
    )
    monkeypatch.setattr(start_mod, "probe", lambda *_a, **_k: "mine")

    reused = start_mod.find_reusable_server(project)
    assert reused == "http://127.0.0.1:8000"


def test_find_reusable_server_none_when_probe_says_other(monkeypatch, tmp_path):
    """A2 identity guard: pid alive + reachable but a DIFFERENT project's
    server answered (e.g. via the global registry pointing at someone else's
    port) => not reusable."""
    registry = {str(tmp_path): {"pid": 4242, "base_url": "http://127.0.0.1:8000"}}
    monkeypatch.setattr(start_mod, "is_process_alive", lambda _pid: True)
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.get_registry", lambda: registry
    )
    monkeypatch.setattr(start_mod, "probe", lambda *_a, **_k: "other")
    assert start_mod.find_reusable_server(tmp_path) is None


def test_find_reusable_server_none_when_pid_dead(monkeypatch, tmp_path):
    registry = {str(tmp_path): {"pid": 4242, "base_url": "http://127.0.0.1:8000"}}
    monkeypatch.setattr(start_mod, "is_process_alive", lambda _pid: False)
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.get_registry", lambda: registry
    )
    monkeypatch.setattr(start_mod, "probe", lambda *_a, **_k: "mine")
    assert start_mod.find_reusable_server(tmp_path) is None


def test_find_reusable_server_none_when_not_in_registry(monkeypatch, tmp_path):
    monkeypatch.setattr("brainpalace_cli.commands.list_cmd.get_registry", lambda: {})
    assert start_mod.find_reusable_server(tmp_path) is None


def test_start_reuse_path_prints_dashboard_box(monkeypatch, tmp_path):
    """Regression: the reuse-live-server branch must still autostart the dashboard
    AND print its hot_pink URL box. Commit 058b00d3 added the reuse branch but
    dropped the `_print_dashboard` call, so a `brainpalace start` against an
    already-running server showed no dashboard box."""
    project = tmp_path
    (project / ".brainpalace").mkdir()
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)
    monkeypatch.setattr(
        "brainpalace_cli.commands.session_hooks.migrate_legacy_sessionstart_hook",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        start_mod,
        "resolve_state_dir_with_fallback",
        lambda _p: project / ".brainpalace",
    )
    monkeypatch.setattr(
        start_mod,
        "read_bind",
        lambda _sd: {
            "bind_host": "127.0.0.1",
            "port_range_start": 8000,
            "port_range_end": 8100,
            "auto_port": True,
        },
    )
    monkeypatch.setattr(
        start_mod, "find_reusable_server", lambda _p: "http://127.0.0.1:8000"
    )
    captured: dict[str, bool] = {}

    def _fake_ensure(*, no_dashboard: bool, json_output: bool):
        captured["called"] = True
        return {"base_url": "http://127.0.0.1:8787", "started": False}

    monkeypatch.setattr(start_mod, "_ensure_dashboard", _fake_ensure)

    result = CliRunner().invoke(start_command, ["--path", str(project)])

    assert result.exit_code == 0, result.output
    assert captured.get("called") is True  # dashboard autostart attempted
    assert "Reusing running server" in result.output
    assert "Web Dashboard" in result.output  # the hot_pink box is back
    assert "8787" in result.output
