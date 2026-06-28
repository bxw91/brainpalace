import os

import pytest

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_distill_service import (
    DEFAULT_IDLE_SECONDS,
    is_marked,
    marker_path,
    pending_sessions,
    progress_path,
    read_progress,
    write_marker,
    write_progress,
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


# --------------------------------------------------------------------------- #
# 2b-1: atomic state writes (temp + os.replace) — no corrupt-on-crash
# --------------------------------------------------------------------------- #
def test_write_progress_roundtrips_no_temp_residue(tmp_path):
    write_progress(
        str(tmp_path), "s1", 12, SessionExtraction(session_id="s1", summary="x")
    )
    off, ext = read_progress(str(tmp_path), "s1")
    assert off == 12 and ext.summary == "x"
    # no leftover *.tmp next to the sidecar
    parent = progress_path(tmp_path, "s1").parent
    assert not list(parent.glob("*.tmp"))


def test_write_marker_no_temp_residue(tmp_path):
    write_marker(tmp_path, "s1")
    assert is_marked(tmp_path, "s1")
    assert not list(marker_path(tmp_path, "s1").parent.glob("*.tmp"))


def test_write_progress_atomic_preserves_prior_on_replace_failure(
    tmp_path, monkeypatch
):
    # Seed a good progress file.
    write_progress(
        str(tmp_path), "s1", 5, SessionExtraction(session_id="s1", summary="good")
    )
    import brainpalace_server.services.session_distill_service as sds

    def _boom(*_a, **_k):
        raise OSError("disk full mid-replace")

    monkeypatch.setattr(sds.os, "replace", _boom)
    # A write that fails at the atomic-commit step must NOT clobber the prior file.
    with pytest.raises(OSError):
        write_progress(
            str(tmp_path), "s1", 99, SessionExtraction(session_id="s1", summary="bad")
        )
    off, ext = read_progress(str(tmp_path), "s1")
    assert off == 5 and ext.summary == "good"  # prior intact, not truncated
    assert not list(
        progress_path(tmp_path, "s1").parent.glob("*.tmp")
    )  # temp cleaned up


def test_write_marker_atomic_preserves_prior_on_replace_failure(tmp_path, monkeypatch):
    write_marker(tmp_path, "s1")
    prior = marker_path(tmp_path, "s1").read_text(encoding="utf-8")
    import brainpalace_server.services.session_distill_service as sds

    monkeypatch.setattr(
        sds.os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom"))
    )
    with pytest.raises(OSError):
        write_marker(tmp_path, "s1")
    assert marker_path(tmp_path, "s1").read_text(encoding="utf-8") == prior
    assert not list(marker_path(tmp_path, "s1").parent.glob("*.tmp"))
