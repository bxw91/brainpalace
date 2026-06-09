"""Start-time server reuse: honour the global registry, not just runtime.json."""

from brainpalace_cli.commands import start as start_mod


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
