import os

from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_distill_service import (
    DEFAULT_IDLE_SECONDS,
    marker_path,
    pending_sessions,
    write_marker,
)


def _archived(tmp_path, sid, *, mtime):
    """Create an archived .jsonl with a given mtime and a manifest entry."""
    svc = SessionArchiveService(tmp_path / "session_archive")
    svc.archive_dir.mkdir(parents=True, exist_ok=True)
    f = svc.archive_dir / f"{sid}.jsonl"
    f.write_text("{}\n")
    os.utime(f, (mtime, mtime))
    svc._manifest[sid] = {  # type: ignore[attr-defined]
        "session_id": sid,
        "archive_path": str(f),
        "src_mtime": mtime,
    }
    svc._save(svc._manifest_path, svc._manifest)  # persist so a fresh svc re-reads
    return svc


def test_pending_includes_new_quiescent_session(tmp_path):
    now = 10_000.0
    _archived(tmp_path, "s1", mtime=now - DEFAULT_IDLE_SECONDS - 1)  # idle → quiescent
    pend = pending_sessions(
        tmp_path,
        tmp_path / "session_archive",
        idle_seconds=DEFAULT_IDLE_SECONDS,
        now=now,
    )
    assert [sid for sid, _ap in pend] == ["s1"]


def test_pending_excludes_active_session(tmp_path):
    now = 10_000.0
    _archived(tmp_path, "s1", mtime=now - 5)  # just touched → NOT quiescent
    pend = pending_sessions(
        tmp_path,
        tmp_path / "session_archive",
        idle_seconds=DEFAULT_IDLE_SECONDS,
        now=now,
    )
    assert pend == []


def test_pending_excludes_marked_unchanged(tmp_path):
    now = 10_000.0
    _archived(tmp_path, "s1", mtime=now - DEFAULT_IDLE_SECONDS - 1)
    write_marker(tmp_path, "s1")  # marker now (newer than archive) → already summarized
    pend = pending_sessions(
        tmp_path,
        tmp_path / "session_archive",
        idle_seconds=DEFAULT_IDLE_SECONDS,
        now=now,
    )
    assert pend == []


def test_pending_reincludes_resumed_session(tmp_path):
    now = 10_000.0
    # marker written in the past, then the archive file grew (newer mtime) → resumed
    write_marker(tmp_path, "s1")
    mp = marker_path(tmp_path, "s1")
    os.utime(mp, (now - 1000, now - 1000))  # marker old
    _archived(
        tmp_path, "s1", mtime=now - DEFAULT_IDLE_SECONDS - 1
    )  # archive newer, quiescent
    pend = pending_sessions(
        tmp_path,
        tmp_path / "session_archive",
        idle_seconds=DEFAULT_IDLE_SECONDS,
        now=now,
    )
    assert [sid for sid, _ap in pend] == ["s1"]


def test_distiller_uses_configured_idle_seconds(tmp_path):
    import asyncio

    from brainpalace_server.services.session_distill_service import SessionDistiller

    class _NoopSummarizer:
        async def summarize(self, *a, **k):  # pragma: no cover - gated out
            return "{}"

    d = SessionDistiller(
        summarizer=_NoopSummarizer(),
        embedder=object(),
        storage_backend=object(),
        project_root=str(tmp_path),
        idle_seconds=99,
    )
    assert d.idle_seconds == 99
    # A single fresh transcript (idle < 99s, no newer sibling) is gated OUT of
    # catch_up by the configured idle_seconds, so nothing is distilled.
    f = tmp_path / "s.jsonl"
    f.write_text("{}\n")
    assert asyncio.run(d.catch_up([f])) == 0
