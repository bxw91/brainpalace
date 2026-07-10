"""Ingested chunks (source_type='ingest') are NOT orphans: no reconcile or
eviction sweep may delete them (spec Item 3 §3.1 — "a sweep that treats them
as orphans would silently delete ingested memory").

The exemption is structural: every deletion sweep enumerates the store through
a source_type filter (session_turn / git_commit / {code,doc}) or through
folder-manifest / folder-record chunk ids. An `ingest` chunk matches none of
those, so it is never even enumerated as a deletion candidate. These fakes
honor the real ``where`` filter so the tests pin that structural exemption and
fail loudly if a future sweep starts from "all chunk ids in the store".
"""

from __future__ import annotations

from typing import Any

import pytest

from brainpalace_server.services.folder_manager import FolderManager
from brainpalace_server.services.manifest_tracker import (
    FileRecord,
    FolderManifest,
    ManifestTracker,
)
from brainpalace_server.services.startup_reconcile import (
    DeepCleanSummary,
    prune_orphan_session_chunks,
    reconcile_orphan_chunks,
)


class _FilterStore:
    """Fake storage backend that honors a metadata ``where`` filter, mirroring
    VectorStoreManager.get_ids_by_where / get_id_source_pairs. Records every
    delete_by_ids batch so tests can assert what was (and was not) deleted."""

    def __init__(self, rows: dict[str, dict[str, Any]]):
        self.rows = dict(rows)
        self.deleted_batches: list[list[str]] = []

    @staticmethod
    def _match(meta: dict[str, Any], where: dict[str, Any]) -> bool:
        for key, cond in where.items():
            val = meta.get(key)
            if isinstance(cond, dict) and "$in" in cond:
                if val not in cond["$in"]:
                    return False
            elif val != cond:
                return False
        return True

    async def get_id_source_pairs(self, where: dict[str, Any]) -> list[tuple[str, str]]:
        return [
            (cid, r.get("source", ""))
            for cid, r in self.rows.items()
            if self._match(r, where)
        ]

    async def get_ids_by_metadata(self, where: dict[str, Any]) -> set[str]:
        return {cid for cid, r in self.rows.items() if self._match(r, where)}

    async def delete_by_ids(self, ids: list[str]) -> int:
        ids = list(ids)
        self.deleted_batches.append(ids)
        for cid in ids:
            self.rows.pop(cid, None)
        return len(ids)

    def all_deleted(self) -> set[str]:
        return {cid for batch in self.deleted_batches for cid in batch}


@pytest.mark.asyncio
async def test_session_orphan_prune_ignores_ingest_chunks(tmp_path):
    # An ingest chunk sits in the store next to a genuinely-orphaned
    # session_turn chunk (its transcript is gone from disk). The session
    # sweep must reap the session orphan and leave the ingest chunk untouched.
    gone_transcript = str(tmp_path / "gone.jsonl")  # never created → orphan
    store = _FilterStore(
        {
            "session:s1:c0": {
                "source_type": "session_turn",
                "source": gone_transcript,
            },
            "ing_abc": {"source_type": "ingest", "source": "ingest://home/x/s1"},
        }
    )
    summary = DeepCleanSummary()
    # archive_dir=tmp_path exists → the sweep proceeds (does not bail out).
    await prune_orphan_session_chunks(store, tmp_path, summary)

    assert "session:s1:c0" in store.all_deleted()  # session orphan reaped
    assert "ing_abc" not in store.all_deleted()  # ingest chunk survives
    assert "ing_abc" in store.rows


@pytest.mark.asyncio
async def test_reconcile_orphan_chunks_ignores_ingest_chunks(tmp_path):
    # reconcile_orphan_chunks is the most dangerous sweep — it starts from the
    # store's live ids and deletes those referenced by no folder manifest. It
    # is hard-scoped to source_type in {code, doc}; an ingest chunk must never
    # be enumerated, so re-ingested memory survives a deep clean.
    folder = str(tmp_path / "proj")
    (tmp_path / "proj").mkdir()

    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()
    await fm.add_folder(
        folder_path=folder,
        chunk_count=1,
        chunk_ids=["code_keep"],
        watch_mode="auto",
        include_code=True,
    )
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")
    man = FolderManifest(folder_path=folder)
    man.files["a.py"] = FileRecord(checksum="x", mtime=1.0, chunk_ids=["code_keep"])
    await mt.save(man)

    store = _FilterStore(
        {
            "code_keep": {"source_type": "code"},  # referenced by manifest
            "code_orphan": {"source_type": "code"},  # referenced by nothing
            "ing_abc": {"source_type": "ingest"},  # must be exempt
        }
    )
    summary = DeepCleanSummary()
    await reconcile_orphan_chunks(fm, mt, store, summary)

    assert "code_orphan" in store.all_deleted()  # code orphan reaped
    assert "ing_abc" not in store.all_deleted()  # ingest chunk survives
    assert "ing_abc" in store.rows
    assert "code_keep" in store.rows  # manifest-referenced chunk kept
