import json
from pathlib import Path

import brainpalace_server.registry as reg


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def test_upsert_creates_and_merges(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    monkeypatch.setattr(reg, "registry_path", lambda: registry)

    reg.upsert_entry(Path("/proj/a"), Path("/proj/a/.brainpalace"))
    reg.upsert_entry(Path("/proj/b"), Path("/proj/b/.brainpalace"))

    data = _read(registry)
    assert data["/proj/a"] == {
        "state_dir": "/proj/a/.brainpalace",
        "project_name": "a",
    }
    assert data["/proj/b"]["project_name"] == "b"


def test_upsert_tolerates_corrupt_file(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text("{ not json")
    monkeypatch.setattr(reg, "registry_path", lambda: registry)

    reg.upsert_entry(Path("/proj/a"), Path("/proj/a/.brainpalace"))
    assert _read(registry)["/proj/a"]["project_name"] == "a"


def test_remove_entry_drops_only_target(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    monkeypatch.setattr(reg, "registry_path", lambda: registry)
    reg.upsert_entry(Path("/proj/a"), Path("/proj/a/.brainpalace"))
    reg.upsert_entry(Path("/proj/b"), Path("/proj/b/.brainpalace"))

    reg.remove_entry(Path("/proj/a"))
    data = _read(registry)
    assert "/proj/a" not in data
    assert "/proj/b" in data


def test_concurrent_upserts_no_lost_update(tmp_path, monkeypatch):
    import threading

    registry = tmp_path / "registry.json"
    monkeypatch.setattr(reg, "registry_path", lambda: registry)

    def add(i: int):
        reg.upsert_entry(Path(f"/proj/{i}"), Path(f"/proj/{i}/.brainpalace"))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = _read(registry)
    assert len(data) == 20  # no entry lost to a racing read-modify-write
