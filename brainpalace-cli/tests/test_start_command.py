"""Start-time server reuse: honour the global registry, not just runtime.json."""

from click.testing import CliRunner

from brainpalace_cli.commands import start as start_mod
from brainpalace_cli.commands.start import start_command


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
    monkeypatch.setattr(start_mod, "check_health", lambda *_a, **_k: True)

    reused = start_mod.find_reusable_server(project)
    assert reused == "http://127.0.0.1:8000"


def test_find_reusable_server_none_when_pid_dead(monkeypatch, tmp_path):
    registry = {str(tmp_path): {"pid": 4242, "base_url": "http://127.0.0.1:8000"}}
    monkeypatch.setattr(start_mod, "is_process_alive", lambda _pid: False)
    monkeypatch.setattr(
        "brainpalace_cli.commands.list_cmd.get_registry", lambda: registry
    )
    monkeypatch.setattr(start_mod, "check_health", lambda *_a, **_k: True)
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
    monkeypatch.setattr(start_mod, "read_config", lambda _sd: {})
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
