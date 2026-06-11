from brainpalace_dashboard.services.instances import InstanceService, instance_id


def test_instance_id_is_deterministic_and_urlsafe() -> None:
    a = instance_id("/home/user/projects/foo")
    b = instance_id("/home/user/projects/foo")
    assert a == b
    assert a.isalnum() or "-" in a or "_" in a
    assert instance_id("/home/user/projects/bar") != a


def test_list_merges_running_scan_and_remembers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))  # isolate store
    proj = tmp_path / "foo"
    proj.mkdir()
    fake = [
        {
            "project_root": str(proj),
            "project_name": "foo",
            "state_dir": str(proj / ".brainpalace"),
            "base_url": "http://127.0.0.1:8001",
            "pid": 11,
            "mode": "project",
            "status": "running",
            "started_at": "2026-06-04T00:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances", lambda: fake
    )
    svc = InstanceService()
    rows = svc.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == instance_id(str(proj))
    assert row["name"] == "foo"
    assert row["status"] == "running"
    assert row["base_url"] == "http://127.0.0.1:8001"


def test_stopped_instance_persists_after_it_leaves_the_registry(
    monkeypatch, tmp_path
) -> None:
    """A project the dashboard has seen stays listed (status=stopped) even when
    it is no longer in the running registry — so it remains Start-able."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    proj = tmp_path / "foo"
    proj.mkdir()
    root = str(proj)
    # First pass: it is running -> gets remembered.
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances",
        lambda: [
            {
                "project_root": root,
                "project_name": "foo",
                "state_dir": root + "/.brainpalace",
                "base_url": "http://127.0.0.1:8001",
                "pid": 11,
                "mode": "project",
                "status": "running",
                "started_at": "",
            }
        ],
    )
    svc = InstanceService()
    svc.list()
    # Second pass: registry is now empty (server stopped & deregistered).
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances", lambda: []
    )
    rows = svc.list()
    assert len(rows) == 1
    assert rows[0]["id"] == instance_id(root)
    assert rows[0]["status"] == "stopped"


def test_deleted_project_dir_is_pruned_from_the_fleet_list(
    monkeypatch, tmp_path
) -> None:
    """A known project whose directory is deleted from disk drops off the list
    (and is removed from the durable store) — not shown as a dead 'stopped' row."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    proj = tmp_path / "gone"
    proj.mkdir()
    root = str(proj)
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances",
        lambda: [
            {
                "project_root": root,
                "project_name": "gone",
                "state_dir": root + "/.brainpalace",
                "base_url": "http://127.0.0.1:8001",
                "pid": 11,
                "mode": "project",
                "status": "running",
                "started_at": "",
            }
        ],
    )
    svc = InstanceService()
    svc.list()  # remembers it
    # Project directory is deleted, registry now empty.
    import shutil

    shutil.rmtree(proj)
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances", lambda: []
    )
    assert svc.list() == []
    # And it is gone from the durable store.
    from brainpalace_cli import known_projects

    assert root not in known_projects.load_existing()
