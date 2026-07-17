"""A3 — `scan_instances` must be identity-checked, not bare-200-checked.

Regression cover for the "two running instances, one server" incident: a
copied ``.brainpalace/`` folder's registry entry has a live pid + a base_url
that answers 200 — but for a DIFFERENT project. Before this fix that entry
was reported "running" (or "unhealthy") alongside the true owner. Now
``probe()`` distinguishes "mine" from "other" from "down":

  - "mine"  -> "running"
  - "other" -> dropped from the returned instance list entirely (not
    "unhealthy" -- this server isn't sick, it's just not this project's), and
    the registry entry is left alone (not pruned as stale).
  - "down" + pid alive -> "unhealthy"
  - "down" + pid dead  -> "stale", pruned from the registry as before.

See ``.planning/specs/2026-07-13-identity-checked-server-health.md`` (A3).
"""

from __future__ import annotations

import json

import brainpalace_cli.commands.list_cmd as list_mod


def _registry_entry(project_root, state_dir, *, pid: int, base_url: str):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / list_mod.RUNTIME_FILE).write_text(
        json.dumps({"pid": pid, "base_url": base_url, "mode": "project"})
    )
    return {str(project_root): {"state_dir": str(state_dir), "project_name": "proj"}}


def test_scan_marks_other_dropped_not_unhealthy(tmp_path, monkeypatch):
    """A copy's registry entry pointing at the true owner's live server is
    dropped from the running set entirely — never reported "unhealthy"."""
    copy_root = tmp_path / "copy"
    state_dir = tmp_path / "copy" / ".brainpalace"
    shared_url = "http://127.0.0.1:8000"

    registry = _registry_entry(copy_root, state_dir, pid=999, base_url=shared_url)

    monkeypatch.setattr(list_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(list_mod, "is_process_alive", lambda _pid: True)
    saved: dict = {}
    monkeypatch.setattr(list_mod, "save_registry", lambda r: saved.update(r))

    def fake_probe(base_url, expected_root, timeout=3.0):
        assert base_url == shared_url
        return "other" if str(expected_root) == str(copy_root) else "mine"

    monkeypatch.setattr(list_mod, "probe", fake_probe)

    instances = list_mod.scan_instances()

    assert instances == []  # dropped, not present at all
    # The registry entry for the copy must SURVIVE (not pruned as stale).
    assert str(copy_root) in registry


def test_scan_marks_true_owner_running(tmp_path, monkeypatch):
    """The true owner's own registry entry still resolves to "running"."""
    owner_root = tmp_path / "owner"
    state_dir = owner_root / ".brainpalace"
    base_url = "http://127.0.0.1:8000"
    registry = _registry_entry(owner_root, state_dir, pid=111, base_url=base_url)

    monkeypatch.setattr(list_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(list_mod, "is_process_alive", lambda _pid: True)
    monkeypatch.setattr(list_mod, "save_registry", lambda r: None)
    monkeypatch.setattr(list_mod, "probe", lambda *_a, **_k: "mine")

    instances = list_mod.scan_instances()

    assert len(instances) == 1
    assert instances[0]["status"] == "running"
    assert instances[0]["project_root"] == str(owner_root)


def test_scan_down_with_alive_pid_is_unhealthy(tmp_path, monkeypatch):
    """ "down" (unreachable/non-200) + a live pid => "unhealthy", kept listed."""
    root = tmp_path / "busy"
    state_dir = root / ".brainpalace"
    registry = _registry_entry(root, state_dir, pid=222, base_url="http://x:1")

    monkeypatch.setattr(list_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(list_mod, "is_process_alive", lambda _pid: True)
    monkeypatch.setattr(list_mod, "save_registry", lambda r: None)
    monkeypatch.setattr(list_mod, "probe", lambda *_a, **_k: "down")

    instances = list_mod.scan_instances()

    assert len(instances) == 1
    assert instances[0]["status"] == "unhealthy"


def test_scan_down_with_dead_pid_is_stale_and_pruned(tmp_path, monkeypatch):
    """ "down" + a dead pid => "stale", and the registry entry IS pruned."""
    root = tmp_path / "gone"
    state_dir = root / ".brainpalace"
    registry = _registry_entry(root, state_dir, pid=333, base_url="http://x:1")

    monkeypatch.setattr(list_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(list_mod, "is_process_alive", lambda _pid: False)
    saved: dict = {}
    monkeypatch.setattr(list_mod, "save_registry", lambda r: saved.update(r))
    monkeypatch.setattr(list_mod, "probe", lambda *_a, **_k: "down")

    instances = list_mod.scan_instances()

    assert len(instances) == 1
    assert instances[0]["status"] == "stale"
    assert str(root) not in registry
