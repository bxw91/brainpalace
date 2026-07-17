"""Startup reconcile heals manifest/store drift automatically on server start.

No flags, no reindex: recompute each folder's chunk_count from the authoritative
per-file manifest and purge store chunks the manifest no longer references
(orphans left by past corruption, e.g. a duplicate server). No-op when nothing
drifted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.manifest_tracker import (
    FileRecord,
    FolderManifest,
    ManifestTracker,
)
from brainpalace_server.services.startup_reconcile import (
    DeepCleanSummary,
    deep_clean,
    prune_missing_folders,
    prune_orphan_git_chunks,
    prune_orphan_session_chunks,
    reconcile_folders,
    reconcile_orphan_chunks,
    reconcile_store_against_manifest,
)


def _storage(deleted: int = 0) -> AsyncMock:
    s = AsyncMock()
    s.delete_by_ids = AsyncMock(return_value=deleted)
    return s


async def _seed(tmp_path, folder, chunk_ids, count, manifest_files, *, watch="auto"):
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()
    await fm.add_folder(
        folder_path=folder,
        chunk_count=count,
        chunk_ids=chunk_ids,
        watch_mode=watch,
        include_code=True,
    )
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")
    if manifest_files is not None:
        man = FolderManifest(folder_path=folder)
        for fp, ids in manifest_files.items():
            man.files[fp] = FileRecord(checksum="x", mtime=1.0, chunk_ids=ids)
        await mt.save(man)
    return fm, mt


@pytest.mark.asyncio
async def test_reconcile_heals_inflated_count_and_purges_orphans(tmp_path):
    folder = str(tmp_path / "repo")
    # FolderManager says 5 chunks incl. 2 orphans; manifest truth = a,b,c.
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c", "orphan1", "orphan2"],
        count=5,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage(deleted=2)

    summary = await reconcile_folders(fm, mt, storage)

    # Orphans purged from the store.
    storage.delete_by_ids.assert_awaited_once()
    assert sorted(storage.delete_by_ids.call_args[0][0]) == ["orphan1", "orphan2"]
    # FolderManager count healed to truth.
    rec = await fm.get_folder(folder)
    assert rec.chunk_count == 3
    assert sorted(rec.chunk_ids) == ["a", "b", "c"]
    # Settings preserved.
    assert rec.watch_mode == "auto"
    assert rec.include_code is True
    # Summary.
    assert summary.folders_healed == 1
    assert summary.chunks_purged == 2


@pytest.mark.asyncio
async def test_reconcile_noop_when_consistent(tmp_path):
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c"],
        count=3,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage()

    summary = await reconcile_folders(fm, mt, storage)

    storage.delete_by_ids.assert_not_called()
    assert summary.folders_healed == 0
    assert summary.chunks_purged == 0


@pytest.mark.asyncio
async def test_reconcile_skips_folder_without_manifest(tmp_path):
    """No per-file manifest => no ground truth; leave the folder untouched."""
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b"],
        count=2,
        manifest_files=None,
    )
    storage = _storage()

    summary = await reconcile_folders(fm, mt, storage)

    storage.delete_by_ids.assert_not_called()
    rec = await fm.get_folder(folder)
    assert rec.chunk_count == 2  # untouched
    assert summary.folders_healed == 0


def _storage_existing(present_ids):
    """Backend whose get_existing_ids reports only `present_ids` as alive."""
    from unittest.mock import AsyncMock

    s = AsyncMock()
    s.get_existing_ids = AsyncMock(return_value=set(present_ids))
    return s


@pytest.mark.asyncio
async def test_store_reconcile_marks_files_with_lost_chunks(tmp_path):
    # Manifest claims x.py=[a,b] and y.py=[c]; the store lost c. y.py must be
    # MARKED pending_reindex — record + chunk ids retained so recovery keeps
    # wanting them and deep-clean spares the surviving chunks. The record is
    # replaced only when the reindex verifies (add-then-swap in the pipeline).
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c"],
        count=3,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage_existing({"a", "b"})  # c is gone

    summary = await reconcile_store_against_manifest(fm, mt, storage)

    assert summary.folders_repaired == 1
    assert summary.files_dropped == 1  # counts files marked for reindex
    # Record retained, marked, ids intact.
    man = await mt.load(folder)
    assert set(man.files) == {f"{folder}/x.py", f"{folder}/y.py"}
    assert man.files[f"{folder}/y.py"].pending_reindex is True
    assert man.files[f"{folder}/y.py"].chunk_ids == ["c"]
    assert man.files[f"{folder}/x.py"].pending_reindex is False
    # Folder record still references ALL manifest ids (recovery keeps wanting c).
    rec = await fm.get_folder(folder)
    assert sorted(rec.chunk_ids) == ["a", "b", "c"]
    assert rec.chunk_count == 3
    # Never deletes store chunks.
    assert not storage.delete_by_ids.await_count


@pytest.mark.asyncio
async def test_pending_reindex_survives_manifest_roundtrip(tmp_path):
    """pending_reindex must persist across save/load (crash between mark and
    reindex must not lose the retry); legacy manifests default to False."""
    folder = "/proj"
    mt = ManifestTracker(manifests_dir=tmp_path / "m")
    man = FolderManifest(folder_path=folder)
    man.files["/proj/a.py"] = FileRecord(
        checksum="x", mtime=1.0, chunk_ids=["c1"], pending_reindex=True
    )
    man.files["/proj/b.py"] = FileRecord(checksum="y", mtime=1.0, chunk_ids=["c2"])
    await mt.save(man)

    loaded = await mt.load(folder)
    assert loaded.files["/proj/a.py"].pending_reindex is True
    assert loaded.files["/proj/b.py"].pending_reindex is False


@pytest.mark.asyncio
async def test_store_reconcile_noop_when_all_present(tmp_path):
    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b", "c"],
        count=3,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    storage = _storage_existing({"a", "b", "c"})

    summary = await reconcile_store_against_manifest(fm, mt, storage)

    assert summary.folders_repaired == 0
    assert summary.files_dropped == 0
    man = await mt.load(folder)
    assert set(man.files) == {f"{folder}/x.py", f"{folder}/y.py"}


@pytest.mark.asyncio
async def test_store_reconcile_skips_backend_without_existence_probe(tmp_path):
    from unittest.mock import AsyncMock

    folder = str(tmp_path / "repo")
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a"],
        count=1,
        manifest_files={f"{folder}/x.py": ["a"]},
    )
    backend = AsyncMock(spec=[])  # no get_existing_ids attribute

    summary = await reconcile_store_against_manifest(fm, mt, backend)

    assert summary.folders_repaired == 0


# ── deep-clean: missing-folder prune + manifest-orphan chunk sweep ────────────


def _storage_ids(ids, deleted: int = 0) -> AsyncMock:
    """Backend that enumerates `ids` for code/doc and reports `deleted` removed."""
    s = AsyncMock()
    s.get_ids_by_metadata = AsyncMock(return_value=set(ids))
    s.delete_by_ids = AsyncMock(return_value=deleted)
    return s


@pytest.mark.asyncio
async def test_prune_missing_folders_removes_gone_dir(tmp_path):
    """A folder whose dir is gone → evict chunks, delete manifest, drop record."""
    folder = str(tmp_path / "gone")  # never created on disk
    fm, mt = await _seed(
        tmp_path,
        folder,
        chunk_ids=["a", "b"],
        count=2,
        manifest_files={f"{folder}/x.py": ["a", "b"]},
    )
    storage = _storage(deleted=2)
    summary = DeepCleanSummary()

    await prune_missing_folders(fm, mt, storage, summary)

    assert summary.folders_removed == 1
    storage.delete_by_ids.assert_awaited_once()
    assert sorted(storage.delete_by_ids.call_args[0][0]) == ["a", "b"]
    assert await fm.get_folder(folder) is None
    assert await mt.load(folder) is None


@pytest.mark.asyncio
async def test_prune_missing_folders_keeps_existing_dir(tmp_path):
    """A folder that still exists on disk is left alone."""
    folder = tmp_path / "live"
    folder.mkdir()
    fm, mt = await _seed(
        tmp_path,
        str(folder),
        chunk_ids=["a"],
        count=1,
        manifest_files={f"{folder}/x.py": ["a"]},
    )
    storage = _storage()
    summary = DeepCleanSummary()

    await prune_missing_folders(fm, mt, storage, summary)

    assert summary.folders_removed == 0
    storage.delete_by_ids.assert_not_called()
    assert await fm.get_folder(str(folder)) is not None


@pytest.mark.asyncio
async def test_orphan_chunks_deletes_unreferenced(tmp_path):
    """Live code/doc chunks in no manifest are deleted; referenced ones kept."""
    folder = tmp_path / "repo"
    folder.mkdir()
    fm, mt = await _seed(
        tmp_path,
        str(folder),
        chunk_ids=["a", "b", "c"],
        count=3,
        manifest_files={f"{folder}/x.py": ["a", "b"], f"{folder}/y.py": ["c"]},
    )
    # Store has the 3 referenced + 1 orphan that no manifest knows about.
    storage = _storage_ids({"a", "b", "c", "orphanZ"}, deleted=1)
    summary = DeepCleanSummary()

    await reconcile_orphan_chunks(fm, mt, storage, summary)

    storage.delete_by_ids.assert_awaited_once()
    assert storage.delete_by_ids.call_args[0][0] == ["orphanZ"]
    assert summary.orphan_chunks_removed == 1


@pytest.mark.asyncio
async def test_orphan_chunks_refuses_when_no_manifest_union(tmp_path):
    """No manifest union (not-ready) → never delete, even with store ids."""
    folder = tmp_path / "repo"
    folder.mkdir()
    fm, mt = await _seed(
        tmp_path,
        str(folder),
        chunk_ids=["a"],
        count=1,
        manifest_files=None,  # no manifest written
    )
    storage = _storage_ids({"a", "b", "c"})
    summary = DeepCleanSummary()

    await reconcile_orphan_chunks(fm, mt, storage, summary)

    storage.delete_by_ids.assert_not_called()
    assert summary.skipped_reason is not None


@pytest.mark.asyncio
async def test_orphan_chunks_skips_backend_without_enumerate(tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()
    fm, mt = await _seed(
        tmp_path,
        str(folder),
        chunk_ids=["a"],
        count=1,
        manifest_files={f"{folder}/x.py": ["a"]},
    )
    backend = AsyncMock(spec=["delete_by_ids"])  # no get_ids_by_metadata

    summary = DeepCleanSummary()
    await reconcile_orphan_chunks(fm, mt, backend, summary)

    assert summary.orphan_chunks_removed == 0


@pytest.mark.asyncio
async def test_deep_clean_prunes_then_sweeps(tmp_path):
    """deep_clean removes a missing folder, then sweeps remaining orphans."""
    gone = str(tmp_path / "gone")
    live = tmp_path / "live"
    live.mkdir()
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()
    await fm.add_folder(
        folder_path=gone, chunk_count=1, chunk_ids=["g1"], include_code=True
    )
    await fm.add_folder(
        folder_path=str(live), chunk_count=1, chunk_ids=["a"], include_code=True
    )
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")
    gone_man = FolderManifest(folder_path=gone)
    gone_man.files[f"{gone}/z.py"] = FileRecord(
        checksum="x", mtime=1.0, chunk_ids=["g1"]
    )
    await mt.save(gone_man)
    live_man = FolderManifest(folder_path=str(live))
    live_man.files[f"{live}/x.py"] = FileRecord(
        checksum="x", mtime=1.0, chunk_ids=["a"]
    )
    await mt.save(live_man)

    # After the missing-folder prune drops `gone`+g1, the store still lists an
    # extra orphan the sweep should reap.
    storage = AsyncMock()
    storage.delete_by_ids = AsyncMock(return_value=1)
    storage.get_ids_by_metadata = AsyncMock(return_value={"a", "leftoverOrphan"})

    summary = await deep_clean(fm, mt, storage)

    assert summary.folders_removed == 1
    assert summary.orphan_chunks_removed == 1
    assert await fm.get_folder(gone) is None


# ── existence-based session + git chunk purge ─────────────────────────────────


def _storage_pairs(pairs, deleted: int = 0) -> AsyncMock:
    """Backend exposing get_id_source_pairs → (id, source) list."""
    s = AsyncMock()
    s.get_id_source_pairs = AsyncMock(return_value=list(pairs))
    s.delete_by_ids = AsyncMock(return_value=deleted)
    return s


@pytest.mark.asyncio
async def test_session_purge_deletes_chunks_whose_source_is_gone(tmp_path):
    """Session chunks whose transcript file no longer exists are deleted; ones
    whose file still exists are kept."""
    live = tmp_path / "kept.jsonl"
    live.write_text("{}")
    gone = str(tmp_path / "gone.jsonl")  # never created
    storage = _storage_pairs(
        [
            ("session:s1:a", str(live)),
            ("session:s1:b", str(live)),
            ("session:s2:c", gone),
        ],
        deleted=1,
    )
    summary = DeepCleanSummary()

    await prune_orphan_session_chunks(storage, tmp_path, summary)

    storage.delete_by_ids.assert_awaited_once_with(["session:s2:c"])
    assert summary.session_chunks_removed == 1


@pytest.mark.asyncio
async def test_session_purge_skips_when_archive_dir_missing(tmp_path):
    """If the archive dir itself is absent, purge nothing (can't verify)."""
    storage = _storage_pairs([("session:s1:a", str(tmp_path / "x.jsonl"))])
    summary = DeepCleanSummary()

    await prune_orphan_session_chunks(storage, tmp_path / "no-such-archive", summary)

    storage.delete_by_ids.assert_not_called()
    assert summary.session_chunks_removed == 0


@pytest.mark.asyncio
async def test_session_purge_leaves_empty_source(tmp_path):
    """A chunk with no recorded source is left alone (can't verify existence)."""
    storage = _storage_pairs([("session:s1:a", "")])
    summary = DeepCleanSummary()

    await prune_orphan_session_chunks(storage, tmp_path, summary)

    storage.delete_by_ids.assert_not_called()


@pytest.mark.asyncio
async def test_git_purge_removes_unreachable_commits(tmp_path, monkeypatch):
    """git_commit chunks whose sha is not in rev-list --all are deleted."""
    import brainpalace_server.services.startup_reconcile as sr

    storage = AsyncMock()
    storage.get_ids_by_metadata = AsyncMock(
        return_value={"git_commit:aaa", "git_commit:bbb", "git_commit:ccc"}
    )
    storage.delete_by_ids = AsyncMock(return_value=2)
    # Repo currently only has 'aaa' reachable → bbb, ccc are orphaned.
    monkeypatch.setattr(sr, "_current_git_shas", lambda _p: {"aaa"})
    summary = DeepCleanSummary()

    await prune_orphan_git_chunks(storage, str(tmp_path), summary)

    storage.delete_by_ids.assert_awaited_once()
    assert sorted(storage.delete_by_ids.call_args[0][0]) == [
        "git_commit:bbb",
        "git_commit:ccc",
    ]
    assert summary.git_chunks_removed == 2


@pytest.mark.asyncio
async def test_git_purge_skips_when_repo_unresolvable(tmp_path, monkeypatch):
    """rev-list None (not a repo / git error) → never purge."""
    import brainpalace_server.services.startup_reconcile as sr

    storage = AsyncMock()
    storage.get_ids_by_metadata = AsyncMock(return_value={"git_commit:aaa"})
    storage.delete_by_ids = AsyncMock(return_value=0)
    monkeypatch.setattr(sr, "_current_git_shas", lambda _p: None)
    summary = DeepCleanSummary()

    await prune_orphan_git_chunks(storage, str(tmp_path), summary)

    storage.delete_by_ids.assert_not_called()


@pytest.mark.asyncio
async def test_git_purge_empty_repo_purges_all(tmp_path, monkeypatch):
    """An empty rev-list (history wiped) is valid → all git chunks purged."""
    import brainpalace_server.services.startup_reconcile as sr

    storage = AsyncMock()
    storage.get_ids_by_metadata = AsyncMock(return_value={"git_commit:aaa"})
    storage.delete_by_ids = AsyncMock(return_value=1)
    monkeypatch.setattr(sr, "_current_git_shas", lambda _p: set())
    summary = DeepCleanSummary()

    await prune_orphan_git_chunks(storage, str(tmp_path), summary)

    storage.delete_by_ids.assert_awaited_once_with(["git_commit:aaa"])
    assert summary.git_chunks_removed == 1


# ---------------------------------------------------------------------------
# _indexable_git_shas — the self-heal WANTED scope must mirror the git
# indexer's own recorded progress: bounded by its persisted `last_sha` (never
# HEAD, never `rev-list --all`). No `last_sha` recorded => want nothing — a
# commit the async git-history job hasn't reached yet was never lost.
# ---------------------------------------------------------------------------


def _git(repo, *args) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    return path


def _commit(repo, relpath: str, msg: str) -> str:
    f = repo / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(msg)
    _git(repo, "add", str(relpath))
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _git_cfg(**kw):
    from brainpalace_server.config.git_config import GitIndexingConfig

    return GitIndexingConfig(enabled=True, **kw)


def _seed_git_state(state_dir, repo_key: str, sha: str) -> None:
    """Write a git_index_state.json as GitHistoryIndexService would, so
    `_indexable_git_shas` reads the exact same last_sha via the shared
    `load_git_last_sha` helper."""
    import json

    from brainpalace_server.storage_paths import state_file_path

    path = state_file_path(state_dir, "git_index_state.json")
    path.write_text(json.dumps({repo_key: sha}))


def test_indexable_git_shas_follow_last_sha_not_all_refs(tmp_path):
    """Commits reachable only from other branches are NOT indexable — wanting
    them (rev-list --all) reported phantom 'need re-embed' residue forever."""
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_main = _commit(repo, "a.txt", "on main")
    _git(repo, "checkout", "-q", "-b", "side")
    sha_side = _commit(repo, "b.txt", "on side")
    _git(repo, "checkout", "-q", "main")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_main)

    shas = sr._indexable_git_shas(str(repo), config=_git_cfg(), git_state_dir=state_dir)
    assert sha_main in shas
    assert sha_side not in shas


def test_indexable_git_shas_scope_to_project_subdir_in_monorepo(tmp_path):
    """BrainPalace project in a monorepo subfolder: only commits touching the
    subfolder are indexable, not the whole repo's history."""
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "mono")
    sha_sub = _commit(repo, "proj/code.py", "touches project")
    sha_other = _commit(repo, "elsewhere/other.txt", "outside project")
    sub = str(repo / "proj")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, sub, sha_other)  # indexer's last_sha is HEAD

    shas = sr._indexable_git_shas(sub, config=_git_cfg(), git_state_dir=state_dir)
    assert sha_sub in shas
    assert sha_other not in shas


def test_indexable_git_shas_disabled_wants_nothing(tmp_path):
    import brainpalace_server.services.startup_reconcile as sr
    from brainpalace_server.config.git_config import GitIndexingConfig

    repo = _init_repo(tmp_path / "repo")
    sha = _commit(repo, "a.txt", "x")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha)  # even with a recorded last_sha

    shas = sr._indexable_git_shas(
        str(repo), config=GitIndexingConfig(enabled=False), git_state_dir=state_dir
    )
    assert shas == set()


def test_indexable_git_shas_respects_depth_cap(tmp_path):
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "a.txt", "first")
    sha_new = _commit(repo, "b.txt", "second")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_new)

    shas = sr._indexable_git_shas(
        str(repo), config=_git_cfg(depth=1), git_state_dir=state_dir
    )
    assert shas == {sha_new}


def test_indexable_git_shas_no_last_sha_wants_nothing(tmp_path):
    """D2: git indexing has never run for this repo (no state dir / no
    recorded last_sha) => want zero git chunks, matching the empty-manifest
    folder case. This is the core fix: self-heal must not count commits the
    async git-history job hasn't reached yet as lost."""
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "a.txt", "x")

    # No git_state_dir at all.
    assert sr._indexable_git_shas(str(repo), config=_git_cfg()) == set()

    # A state dir that exists but has no entry for this repo.
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert (
        sr._indexable_git_shas(str(repo), config=_git_cfg(), git_state_dir=state_dir)
        == set()
    )


def test_indexable_git_shas_partial_progress_excludes_unindexed_tip(tmp_path):
    """The exact bug scenario: git indexing has recorded progress only up to
    an older commit; a newer commit lands before the async job catches up.
    Self-heal must want only what was indexed, not the live HEAD."""
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_indexed = _commit(repo, "a.txt", "indexed")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_indexed)
    sha_pending = _commit(repo, "b.txt", "not yet indexed")  # async job hasn't run

    shas = sr._indexable_git_shas(str(repo), config=_git_cfg(), git_state_dir=state_dir)

    assert shas == {sha_indexed}
    assert sha_pending not in shas


def test_indexable_git_shas_unreachable_last_sha_returns_none(tmp_path):
    """D4: a recorded last_sha that's no longer reachable (e.g. GC'd after a
    history rewrite) makes the underlying git log fail => None (couldn't
    determine), not an empty set."""
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "a.txt", "x")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), "0" * 40)  # never-existed sha

    shas = sr._indexable_git_shas(str(repo), config=_git_cfg(), git_state_dir=state_dir)
    assert shas is None


def test_indexable_git_shas_not_a_repo_returns_none(tmp_path):
    """Not a repo at all, but a last_sha IS recorded (e.g. the repo dir was
    removed after indexing) — list_indexable_shas' git log fails => None."""
    import brainpalace_server.services.startup_reconcile as sr

    void = str(tmp_path / "void")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, void, "a" * 40)

    assert (
        sr._indexable_git_shas(void, config=_git_cfg(), git_state_dir=state_dir) is None
    )


# ---------------------------------------------------------------------------
# self_heal_on_startup — end-to-end: the git-bounded wanted-set must reach
# chunk_recovery unchanged, so residue is never reported for not-yet-indexed
# commits (the false-positive this fix closes).
# ---------------------------------------------------------------------------


class _MockVectorStore:
    persist_dir = "/tmp"

    async def get_existing_ids(self, ids: list[str]) -> set[str]:
        # Default: every queried id is present live (an already-materialized
        # store). Tests that need a partial/empty git plane override this.
        return set(ids)


@pytest.mark.asyncio
async def test_self_heal_wants_zero_git_ids_on_fresh_repo(tmp_path, monkeypatch):
    """No folders indexed (empty manifest union) and git never indexed (no
    last_sha) => wanted is empty => recover_lost_chunks is never even called,
    so residue is correctly 0 rather than every HEAD commit."""
    from unittest.mock import MagicMock

    import brainpalace_server.config.git_config as git_config
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "a.txt", "first")
    _commit(repo, "b.txt", "second")

    monkeypatch.setattr(
        git_config, "load_git_indexing_config", lambda *a, **kw: _git_cfg()
    )
    recover = AsyncMock()
    monkeypatch.setattr(sr.chunk_recovery, "recover_lost_chunks", recover)

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()

    report = await sr.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=_MockVectorStore(),
        cache_db_path=None,
        target_dimensions=0,
        repo_path=str(repo),
        git_state_dir=tmp_path / "state",  # no state file written — never indexed
    )

    recover.assert_not_called()
    assert report["recovery"] is None


@pytest.mark.asyncio
async def test_self_heal_bounds_git_wanted_set_by_last_sha(tmp_path, monkeypatch):
    """Git indexing recorded progress up to an older commit; a newer commit
    landed since (async job hasn't caught up). The wanted-set reaching
    chunk_recovery must include the indexed commit's chunk and exclude the
    pending one — the exact false-positive scenario from the bug report."""
    from unittest.mock import MagicMock

    import brainpalace_server.config.git_config as git_config
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_indexed = _commit(repo, "a.txt", "indexed")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_indexed)
    _commit(repo, "b.txt", "not yet indexed")  # created after last_sha recorded

    monkeypatch.setattr(
        git_config, "load_git_indexing_config", lambda *a, **kw: _git_cfg()
    )
    captured: dict = {}

    async def _fake_recover(*, wanted_ids, **kwargs):
        captured["wanted_ids"] = set(wanted_ids)
        return sr.chunk_recovery.RecoverySummary()

    monkeypatch.setattr(sr.chunk_recovery, "recover_lost_chunks", _fake_recover)

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()

    await sr.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=_MockVectorStore(),
        cache_db_path=None,
        target_dimensions=0,
        repo_path=str(repo),
        git_state_dir=state_dir,
    )

    assert captured["wanted_ids"] == {f"git_commit:{sha_indexed}"}


@pytest.mark.asyncio
async def test_self_heal_excludes_git_when_store_has_no_git_chunks(
    tmp_path, monkeypatch
):
    """git_index_state.json records a last_sha (a prior life of this repo — a
    fresh/reset store, or a rehome that carried the state forward) but the
    current store holds ZERO git_commit chunks (none live, none in a dead
    segment). The git plane was never materialized here, so chunk_recovery has
    nothing to restore from and would otherwise report every recorded commit as
    residue ("N chunks need re-embed") — the persistent false alarm this fix
    closes. The always-enqueued git boot-index job rebuilds the plane instead.
    => git ids must be excluded from the wanted-set."""
    from unittest.mock import MagicMock

    import brainpalace_server.config.git_config as git_config
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_indexed = _commit(repo, "a.txt", "indexed")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_indexed)

    monkeypatch.setattr(
        git_config, "load_git_indexing_config", lambda *a, **kw: _git_cfg()
    )
    captured: dict = {}

    async def _fake_recover(*, wanted_ids, **kwargs):
        captured["wanted_ids"] = set(wanted_ids)
        return sr.chunk_recovery.RecoverySummary()

    monkeypatch.setattr(sr.chunk_recovery, "recover_lost_chunks", _fake_recover)
    # No dead segments either — an empty store.
    monkeypatch.setattr(
        sr.chunk_recovery, "read_recoverable_chunks", lambda _p, _ids: {}
    )

    # Store reports NO git_commit chunk present live.
    class _EmptyGitStore(_MockVectorStore):
        async def get_existing_ids(self, ids):
            return set()

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()

    await sr.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=_EmptyGitStore(),
        cache_db_path=None,
        target_dimensions=0,
        repo_path=str(repo),
        git_state_dir=state_dir,
    )

    # manifest union empty + git suppressed => nothing wanted => recovery skipped.
    assert captured == {}


@pytest.mark.asyncio
async def test_self_heal_keeps_dead_segment_git_id_for_recovery(tmp_path, monkeypatch):
    """A recorded commit is absent from the live collection but present in a
    DEAD segment (a collection rebuild stranded it). Self-heal's git role IS to
    restore that one from dead-text + cache with no re-embed, so it must stay in
    the wanted-set."""
    from unittest.mock import MagicMock

    import brainpalace_server.config.git_config as git_config
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_indexed = _commit(repo, "a.txt", "indexed")
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_indexed)

    monkeypatch.setattr(
        git_config, "load_git_indexing_config", lambda *a, **kw: _git_cfg()
    )
    captured: dict = {}

    async def _fake_recover(*, wanted_ids, **kwargs):
        captured["wanted_ids"] = set(wanted_ids)
        return sr.chunk_recovery.RecoverySummary()

    monkeypatch.setattr(sr.chunk_recovery, "recover_lost_chunks", _fake_recover)
    # Not live, but stranded in a dead segment => recoverable here.
    monkeypatch.setattr(
        sr.chunk_recovery,
        "read_recoverable_chunks",
        lambda _p, ids: {cid: object() for cid in ids},
    )

    class _StrandedGitStore(_MockVectorStore):
        async def get_existing_ids(self, ids):
            return set()  # nothing live — all stranded

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()

    await sr.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=_StrandedGitStore(),
        cache_db_path=None,
        target_dimensions=0,
        repo_path=str(repo),
        git_state_dir=state_dir,
    )

    assert captured["wanted_ids"] == {f"git_commit:{sha_indexed}"}


@pytest.mark.asyncio
async def test_self_heal_drops_never_materialized_git_ids_when_plane_partial(
    tmp_path, monkeypatch
):
    """The regression this fix targets: the git plane is PARTIAL (one commit
    live) while last_sha wants two. The commit the async boot-index job hasn't
    reached — neither live nor in a dead segment — must NOT enter the wanted-set
    (else it is reported as phantom "need re-embed" residue). The binary
    plane-materialized gate wrongly kept it because the store held >=1 chunk."""
    from unittest.mock import MagicMock

    import brainpalace_server.config.git_config as git_config
    import brainpalace_server.services.startup_reconcile as sr

    repo = _init_repo(tmp_path / "repo")
    sha_a = _commit(repo, "a.txt", "materialized")
    sha_b = _commit(repo, "b.txt", "not yet indexed")  # boot job hasn't reached it
    state_dir = tmp_path / "state"
    _seed_git_state(state_dir, str(repo), sha_b)  # last_sha wants both a and b

    monkeypatch.setattr(
        git_config, "load_git_indexing_config", lambda *a, **kw: _git_cfg()
    )
    captured: dict = {}

    async def _fake_recover(*, wanted_ids, **kwargs):
        captured["wanted_ids"] = set(wanted_ids)
        return sr.chunk_recovery.RecoverySummary()

    monkeypatch.setattr(sr.chunk_recovery, "recover_lost_chunks", _fake_recover)
    # No dead segments — b was never in this store at all.
    monkeypatch.setattr(
        sr.chunk_recovery, "read_recoverable_chunks", lambda _p, _ids: {}
    )

    live_a = {f"git_commit:{sha_a}"}

    class _PartialGitStore(_MockVectorStore):
        async def get_existing_ids(self, ids):
            return live_a & set(ids)  # only a is materialized

    folder_manager = MagicMock()
    folder_manager.list_folders = AsyncMock(return_value=[])
    manifest_tracker = MagicMock()

    await sr.self_heal_on_startup(
        folder_manager=folder_manager,
        manifest_tracker=manifest_tracker,
        storage_backend=MagicMock(),
        vector_store=_PartialGitStore(),
        cache_db_path=None,
        target_dimensions=0,
        repo_path=str(repo),
        git_state_dir=state_dir,
    )

    # a stays (live); b is dropped (never materialized) => no phantom residue.
    assert captured["wanted_ids"] == live_a
