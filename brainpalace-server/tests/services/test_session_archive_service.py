import json as _json
from pathlib import Path

from brainpalace_server.services.session_archive_service import SessionArchiveService


def test_tombstone_roundtrip(tmp_path: Path) -> None:
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    assert svc.is_tombstoned("s1") is False
    svc.tombstone("s1", origin_path="/home/u/.claude/projects/p/s1.jsonl")
    assert svc.is_tombstoned("s1") is True
    # Persisted: a fresh instance over the same dir still sees it.
    svc2 = SessionArchiveService(archive_dir=tmp_path / "arch")
    assert svc2.is_tombstoned("s1") is True


def test_corrupt_manifest_is_treated_as_empty(tmp_path: Path) -> None:
    arch = tmp_path / "arch"
    arch.mkdir(parents=True)
    (arch / "manifest.json").write_text("{not json")
    svc = SessionArchiveService(archive_dir=arch)
    assert svc.manifest_entry("anything") is None  # no crash


def _write_transcript(path: Path, session_id: str, started_at: str) -> None:
    """Minimal Claude-style JSONL the loader can parse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "sessionId": session_id,
        "timestamp": started_at,
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }
    path.write_text(_json.dumps(line) + "\n", encoding="utf-8")


def test_sync_copies_into_dated_folder(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_abc.jsonl"
    _write_transcript(live, "s_abc", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")

    archive_path = svc.sync(live)

    assert archive_path is not None
    # Folder is tool-tagged YYYY-MM-DD-<tool> (default claude-code).
    assert archive_path == tmp_path / "arch" / "2026-06-01-claude-code" / "s_abc.jsonl"
    assert archive_path.read_text() == live.read_text()  # verbatim
    entry = svc.manifest_entry("s_abc")
    assert entry["origin_path"] == str(live)
    assert entry["tool"] == "claude-code"  # structured field = source of truth
    assert entry["archived_date"] == "2026-06-01"  # bare date unchanged
    assert entry["archived_dir"] == "2026-06-01-claude-code"


def test_custom_tool_slug_in_folder_and_manifest(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_t.jsonl"
    _write_transcript(live, "s_t", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch", tool="codex")
    dest = svc.sync(live)
    assert dest == tmp_path / "arch" / "2026-06-01-codex" / "s_t.jsonl"
    assert svc.manifest_entry("s_t")["tool"] == "codex"


def test_sync_skips_tombstoned(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_x.jsonl"
    _write_transcript(live, "s_x", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    svc.tombstone("s_x", origin_path=str(live))

    assert svc.sync(live) is None
    assert not (tmp_path / "arch" / "2026-06-01-claude-code" / "s_x.jsonl").exists()


def test_sync_unchanged_is_noop(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_y.jsonl"
    _write_transcript(live, "s_y", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    first = svc.sync(live)
    second = svc.sync(live)  # nothing changed
    assert first == second
    assert second is not None  # returns the path, but did not re-copy


def test_resume_overwrites_same_file(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_z.jsonl"
    _write_transcript(live, "s_z", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive_path = svc.sync(live)
    # Resume days later: append a turn (mtime/size change), same session_id/date.
    with live.open("a", encoding="utf-8") as f:
        f.write(
            _json.dumps(
                {
                    "sessionId": "s_z",
                    "timestamp": "2026-06-05T09:00:00Z",
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "more"}],
                    },
                }
            )
            + "\n"
        )
    again = svc.sync(live)
    assert again == archive_path  # same file, original started_at date
    assert again.read_text() == live.read_text()  # overwritten with full content


def test_reconcile_deletions_returns_missing_and_tombstones(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_del.jsonl"
    _write_transcript(live, "s_del", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive_path = svc.sync(live)
    assert archive_path.exists()

    archive_path.unlink()  # user curates it away
    removed = svc.reconcile_deletions()

    assert removed == ["s_del"]
    assert svc.is_tombstoned("s_del") is True
    assert svc.manifest_entry("s_del") is None
    # And a later sync of the still-present live source does NOT resurrect it.
    assert svc.sync(live) is None


def test_reconcile_noop_when_nothing_deleted(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_keep.jsonl"
    _write_transcript(live, "s_keep", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    svc.sync(live)
    assert svc.reconcile_deletions() == []


def test_stats_counts_sessions_and_tombstones(tmp_path: Path) -> None:
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    for sid in ("a", "b"):
        live = tmp_path / "live" / f"{sid}.jsonl"
        _write_transcript(live, sid, "2026-06-01T10:00:00Z")
        svc.sync(live)
    svc.tombstone("gone", origin_path="/x")
    stats = svc.stats()
    assert stats["archived_sessions"] == 2
    assert stats["tombstoned"] == 1
    assert stats["archived_bytes"] > 0


def test_backfill_syncs_all_and_is_idempotent(tmp_path: Path) -> None:
    paths = []
    for sid in ("a", "b"):
        live = tmp_path / "live" / f"{sid}.jsonl"
        _write_transcript(live, sid, "2026-06-01T10:00:00Z")
        paths.append(live)
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    produced = svc.backfill(paths)
    assert len(produced) == 2
    # Second run: unchanged -> still returns the archive paths, no errors.
    again = svc.backfill(paths)
    assert sorted(map(str, again)) == sorted(map(str, produced))


# --- subagent manifest-key collision (parent sessionId shared) ---


def _write_subagent(
    sessions_dir: Path, parent_id: str, agent: str, started_at: str
) -> Path:
    """Subagent transcript: lives under <parent_id>/subagents/ and carries the
    PARENT's sessionId (matches real Claude layout)."""
    p = sessions_dir / parent_id / "subagents" / f"{agent}.jsonl"
    _write_transcript(p, parent_id, started_at)  # sessionId == parent_id
    return p


def test_subagent_keyed_separately_from_parent(tmp_path: Path) -> None:
    sdir = tmp_path / "live"
    parent = sdir / "P.jsonl"
    _write_transcript(parent, "P", "2026-06-01T10:00:00Z")
    sub = _write_subagent(sdir, "P", "agent-x", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")

    pdest = svc.sync(parent)
    sdest = svc.sync(sub)

    # Distinct destinations, both archived (parent NOT overwritten by subagent).
    # Subagent nests under the parent's tool-tagged dated folder.
    assert pdest == tmp_path / "arch" / "2026-06-01-claude-code" / "P.jsonl"
    assert (
        sdest
        == tmp_path
        / "arch"
        / "2026-06-01-claude-code"
        / "P"
        / "subagents"
        / "agent-x.jsonl"
    )
    assert pdest.exists() and sdest.exists()
    # Two manifest entries (one per file), but one distinct session.
    st = svc.stats()
    assert st["archived_files"] == 2
    assert st["archived_sessions"] == 1


def test_subagent_only_deletion_does_not_purge_parent(tmp_path: Path) -> None:
    sdir = tmp_path / "live"
    parent = sdir / "P.jsonl"
    _write_transcript(parent, "P", "2026-06-01T10:00:00Z")
    sub = _write_subagent(sdir, "P", "agent-x", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    svc.sync(parent)
    sdest = svc.sync(sub)

    sdest.unlink()  # delete ONLY the subagent archive file
    purged = svc.reconcile_deletions()

    # Parent session NOT purged (its file survives).
    assert purged == []
    # Parent still archived + present; subagent gone.
    assert svc.stats()["archived_files"] == 1
    assert svc.stats()["archived_sessions"] == 1


def test_full_session_deletion_purges_once(tmp_path: Path) -> None:
    sdir = tmp_path / "live"
    parent = sdir / "P.jsonl"
    _write_transcript(parent, "P", "2026-06-01T10:00:00Z")
    sub = _write_subagent(sdir, "P", "agent-x", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    pdest = svc.sync(parent)
    sdest = svc.sync(sub)

    pdest.unlink()
    sdest.unlink()  # whole session removed (both files)
    purged = svc.reconcile_deletions()

    assert purged == ["P"]  # one purge for the session, not per-file
    assert svc.stats()["archived_files"] == 0
