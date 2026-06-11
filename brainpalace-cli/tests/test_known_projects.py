"""Durable known-projects store: remember / forget / prune-missing."""

from __future__ import annotations

import json

import pytest

from brainpalace_cli import known_projects


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Point the XDG state dir at a temp dir so tests never touch real state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    yield


def test_remember_persists_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    known_projects.remember(proj, proj / ".brainpalace", "proj")
    known = known_projects.load_existing()
    root = str(proj.resolve())
    assert root in known
    assert known[root]["project_name"] == "proj"
    assert known[root]["state_dir"] == str(proj / ".brainpalace")


def test_remember_is_idempotent_no_rewrite(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    known_projects.remember(proj, proj / ".brainpalace", "proj")
    mtime1 = known_projects._path().stat().st_mtime_ns
    known_projects.remember(proj, proj / ".brainpalace", "proj")
    assert known_projects._path().stat().st_mtime_ns == mtime1  # unchanged → no write


def test_forget_removes_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    known_projects.remember(proj, proj / ".brainpalace", "proj")
    assert known_projects.forget(proj) is True
    assert str(proj.resolve()) not in known_projects.load_existing()
    assert known_projects.forget(proj) is False  # already gone


def test_prune_missing_drops_deleted_dirs(tmp_path):
    alive = tmp_path / "alive"
    alive.mkdir()
    dead = tmp_path / "dead"
    dead.mkdir()
    known_projects.remember(alive, alive / ".brainpalace", "alive")
    known_projects.remember(dead, dead / ".brainpalace", "dead")
    # Delete one project's directory from disk.
    dead.rmdir()

    removed = known_projects.prune_missing()
    assert removed == [str(dead.resolve())]

    existing = known_projects.load_existing()
    assert str(alive.resolve()) in existing
    assert str(dead.resolve()) not in existing
    # The removal was persisted.
    on_disk = json.loads(known_projects._path().read_text())
    assert str(dead.resolve()) not in on_disk


def test_load_existing_prunes_before_returning(tmp_path):
    dead = tmp_path / "dead"
    dead.mkdir()
    known_projects.remember(dead, dead / ".brainpalace", "dead")
    dead.rmdir()
    assert known_projects.load_existing() == {}


def test_corrupt_store_is_tolerated(tmp_path):
    path = known_projects._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert known_projects.load_existing() == {}
