import asyncio
from pathlib import Path

from brainpalace_server.services.session_reconciler import reconcile_once


class _FakeArchive:
    def __init__(self):
        self.synced = []

    def sync(self, live):
        self.synced.append(Path(live))
        return Path(str(live) + ".arch")  # pretend-archived path


class _FakeDistiller:
    def __init__(self):
        self.caught_up = None

    async def catch_up(self, transcripts):
        self.caught_up = [Path(p) for p in transcripts]
        return len(self.caught_up)


class _Caps:
    index_enabled = False


class _Cfg:
    retain_days = 0
    include_user_turns = False
    window = 4
    stride = 2


def _patch_helpers(monkeypatch):
    monkeypatch.setattr(
        "brainpalace_server.services.session_reconciler.discover_session_files",
        lambda d: sorted(Path(d).glob("*.jsonl")),
    )
    monkeypatch.setattr(
        "brainpalace_server.services.session_reconciler.retain_cutoff",
        lambda days: None,
    )


def test_reconcile_once_syncs_each_live_file(tmp_path, monkeypatch):
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    (sdir / "a.jsonl").write_text("{}\n")
    (sdir / "b.jsonl").write_text("{}\n")
    _patch_helpers(monkeypatch)
    arch = _FakeArchive()
    res = asyncio.run(
        reconcile_once(
            sessions_dir=sdir,
            archive_service=arch,
            sess_svc=None,
            session_cfg=_Cfg(),
            caps=_Caps(),
            distiller=None,
        )
    )
    assert res["archived"] == 2
    assert sorted(p.name for p in arch.synced) == ["a.jsonl", "b.jsonl"]


def test_reconciler_tick_runs_one_sweep(tmp_path, monkeypatch):
    from brainpalace_server.services import session_reconciler as sr

    calls = {"n": 0}

    async def fake_once(**kw):
        calls["n"] += 1
        return {"archived": 0, "indexed": 0}

    monkeypatch.setattr(sr, "reconcile_once", fake_once)
    rec = sr.SessionReconciler(
        interval_seconds=600,
        sessions_dir=tmp_path,
        archive_service=None,
        sess_svc=None,
        session_cfg=_Cfg(),
        caps=_Caps(),
        distiller=None,
    )
    asyncio.run(rec._tick())
    assert calls["n"] == 1


def test_tick_invokes_memory_curator(tmp_path, monkeypatch):
    from brainpalace_server.services import session_reconciler as sr

    async def fake_once(**kw):
        return {"archived": 0, "indexed": 0}

    monkeypatch.setattr(sr, "reconcile_once", fake_once)

    class _Curator:
        def __init__(self):
            self.state_dir = None

        async def curate_if_due(self, state_dir):
            self.state_dir = state_dir
            return 0

    cur = _Curator()
    rec = sr.SessionReconciler(
        interval_seconds=600,
        sessions_dir=tmp_path,
        archive_service=None,
        sess_svc=None,
        session_cfg=_Cfg(),
        caps=_Caps(),
        distiller=None,
        memory_curator=cur,
        curate_state_dir=tmp_path,
    )
    asyncio.run(rec._tick())
    assert cur.state_dir == tmp_path  # curate_if_due awaited with the state dir


def test_tick_no_curator_is_noop(tmp_path, monkeypatch):
    from brainpalace_server.services import session_reconciler as sr

    async def fake_once(**kw):
        return {"archived": 0, "indexed": 0}

    monkeypatch.setattr(sr, "reconcile_once", fake_once)
    rec = sr.SessionReconciler(
        interval_seconds=600,
        sessions_dir=tmp_path,
        archive_service=None,
        sess_svc=None,
        session_cfg=_Cfg(),
        caps=_Caps(),
        distiller=None,
    )
    # No memory_curator wired → _tick completes without error.
    assert asyncio.run(rec._tick()) == {"archived": 0, "indexed": 0}


def test_distiller_runs_on_live_when_archive_off(tmp_path, monkeypatch):
    """Archive (copy) OFF + extraction ON: the distiller summarizes the LIVE
    source transcripts — the three capabilities are independent."""
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    (sdir / "a.jsonl").write_text("{}\n")
    (sdir / "b.jsonl").write_text("{}\n")
    _patch_helpers(monkeypatch)
    dist = _FakeDistiller()
    res = asyncio.run(
        reconcile_once(
            sessions_dir=sdir,
            archive_service=None,  # copy OFF
            sess_svc=None,  # index OFF
            session_cfg=_Cfg(),
            caps=_Caps(),
            distiller=dist,
        )
    )
    assert res["archived"] == 0
    # Distiller got the live source paths, not archive copies.
    assert sorted(p.name for p in dist.caught_up) == ["a.jsonl", "b.jsonl"]
    assert all(str(p).endswith(".jsonl") for p in dist.caught_up)


def test_distiller_runs_on_archive_when_archiving(tmp_path, monkeypatch):
    """Archive ON: the distiller summarizes the archived copies (unchanged)."""
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    (sdir / "a.jsonl").write_text("{}\n")
    _patch_helpers(monkeypatch)
    dist = _FakeDistiller()
    asyncio.run(
        reconcile_once(
            sessions_dir=sdir,
            archive_service=_FakeArchive(),
            sess_svc=None,
            session_cfg=_Cfg(),
            caps=_Caps(),
            distiller=dist,
        )
    )
    assert [p.name for p in dist.caught_up] == ["a.jsonl.arch"]


def test_reconcile_once_offers_files_every_sweep(tmp_path, monkeypatch):
    # reconcile_once calls sync() every sweep; the *service* dedups unchanged
    # files. Here we assert reconcile_once doesn't filter on its own.
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    (sdir / "a.jsonl").write_text("{}\n")
    _patch_helpers(monkeypatch)
    arch = _FakeArchive()
    for _ in range(2):
        asyncio.run(
            reconcile_once(
                sessions_dir=sdir,
                archive_service=arch,
                sess_svc=None,
                session_cfg=_Cfg(),
                caps=_Caps(),
                distiller=None,
            )
        )
    assert len(arch.synced) == 2  # offered twice; real sync() would no-op the 2nd
