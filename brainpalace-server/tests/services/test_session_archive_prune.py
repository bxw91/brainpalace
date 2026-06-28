"""Archive retention: the durable transcript archive must honor retain_days so
it can't grow forever (it holds full transcripts incl. secrets)."""

import datetime

from brainpalace_server.services.session_archive_service import SessionArchiveService


def _folder(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    (d / "s.jsonl").write_text("x")
    return d


def test_prune_removes_folders_older_than_retain_days(tmp_path):
    svc = SessionArchiveService(tmp_path, tool="claude-code")
    old = _folder(tmp_path, "2026-01-01-claude-code")
    recent = _folder(tmp_path, "2026-06-27-claude-code")

    removed = svc.prune(retain_days=30, now=datetime.date(2026, 6, 28))

    assert "2026-01-01-claude-code" in removed
    assert not old.exists()
    assert recent.exists()


def test_prune_zero_keeps_forever(tmp_path):
    svc = SessionArchiveService(tmp_path, tool="claude-code")
    old = _folder(tmp_path, "2026-01-01-claude-code")

    removed = svc.prune(retain_days=0, now=datetime.date(2026, 6, 28))

    assert removed == []
    assert old.exists()


def test_prune_drops_manifest_entries_for_removed_folder(tmp_path):
    svc = SessionArchiveService(tmp_path, tool="claude-code")
    _folder(tmp_path, "2026-01-01-claude-code")
    svc._put_manifest(
        "sess1",
        {"archived_dir": "2026-01-01-claude-code", "session_id": "sess1"},
    )

    svc.prune(retain_days=30, now=datetime.date(2026, 6, 28))

    assert svc.manifest_entry("sess1") is None


def test_prune_ignores_undated_and_files(tmp_path):
    svc = SessionArchiveService(tmp_path, tool="claude-code")
    undated = _folder(tmp_path, "undated-claude-code")
    (tmp_path / "manifest.json").write_text("{}")

    removed = svc.prune(retain_days=1, now=datetime.date(2026, 6, 28))

    assert removed == []
    assert undated.exists()
