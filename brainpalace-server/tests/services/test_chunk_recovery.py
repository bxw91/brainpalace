"""Recover lost vector chunks from dead Chroma segments + the embedding cache.

A collection recreation (heal rebuild / duplicate-server stomp) strands a
segment: its rows survive in ``chroma.sqlite3`` *below* the collection API —
chunk text + metadata intact, vectors gone (the HNSW dir was pruned). The
embedding cache still holds the vector keyed by ``SHA256(text)``. This module
restores the manifest's missing chunks into the live collection from those two
survivors, with **no re-embed and no external provider call**.
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from pathlib import Path

import pytest

from brainpalace_server.services.chunk_recovery import (
    RecoverySummary,
    detect_dimensions,
    load_cache_vectors,
    read_recoverable_chunks,
    rebuild_bm25_from_collection,
    recover_lost_chunks,
)
from brainpalace_server.storage.vector_store import VectorStoreManager


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_chroma_sqlite(path, *, live_seg, dead_seg, live, dead) -> None:
    """A minimal Chroma sqlite: ``live_seg`` is in ``segments`` (alive), ``dead_seg``
    is referenced only by embeddings (dead/orphaned)."""
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT NOT NULL,
            scope TEXT NOT NULL, collection TEXT NOT NULL);
        CREATE TABLE embeddings(id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL,
            embedding_id TEXT NOT NULL, seq_id BLOB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(segment_id, embedding_id));
        CREATE TABLE embedding_metadata(id INTEGER, key TEXT NOT NULL,
            string_value TEXT, int_value INTEGER, float_value REAL,
            bool_value INTEGER, PRIMARY KEY(id, key));
        """
    )
    con.execute(
        "INSERT INTO segments VALUES(?,?,?,?)", (live_seg, "metadata", "METADATA", "c")
    )
    rid = 0

    def add(seg, chunks):
        nonlocal rid
        for eid, (text, meta) in chunks.items():
            rid += 1
            con.execute(
                "INSERT INTO embeddings(id,segment_id,embedding_id,seq_id) "
                "VALUES(?,?,?,?)",
                (rid, seg, eid, bytes([rid % 256, (rid >> 8) % 256])),
            )
            con.execute(
                "INSERT INTO embedding_metadata(id,key,string_value) VALUES(?,?,?)",
                (rid, "chroma:document", text),
            )
            con.execute(
                "INSERT INTO embedding_metadata(id,key,string_value) VALUES(?,?,?)",
                (rid, "chunk_id", eid),
            )
            for k, v in meta.items():
                if isinstance(v, bool):
                    col, val = "bool_value", int(v)
                elif isinstance(v, int):
                    col, val = "int_value", v
                elif isinstance(v, float):
                    col, val = "float_value", v
                else:
                    col, val = "string_value", str(v)
                con.execute(
                    f"INSERT INTO embedding_metadata(id,key,{col}) VALUES(?,?,?)",
                    (rid, k, val),
                )

    add(live_seg, live)
    add(dead_seg, dead)
    con.commit()
    con.close()


def _build_cache(path, entries) -> None:
    """entries: list of (text, provider, model, dims, vector)."""
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE embeddings(cache_key TEXT PRIMARY KEY, embedding BLOB, "
        "provider TEXT, model TEXT, dimensions INTEGER, last_accessed REAL)"
    )
    for text, provider, model, dims, vec in entries:
        key = f"{_sha(text)}:{provider}:{model}:{dims}"
        con.execute(
            "INSERT INTO embeddings VALUES(?,?,?,?,?,?)",
            (key, struct.pack(f"{dims}f", *vec), provider, model, dims, 0.0),
        )
    con.commit()
    con.close()


def _inject_dead_row(chroma_db, *, seg, eid, text, meta) -> None:
    """Insert one dead-segment row into a *real* Chroma sqlite (seg absent from
    ``segments`` => orphaned, invisible to the collection API)."""
    con = sqlite3.connect(str(chroma_db))
    mx = con.execute("SELECT COALESCE(MAX(id),0) FROM embeddings").fetchone()[0]
    rid = mx + 1000
    con.execute(
        "INSERT INTO embeddings(id,segment_id,embedding_id,seq_id) VALUES(?,?,?,?)",
        (rid, seg, eid, bytes([rid % 256, (rid >> 8) % 256, (rid >> 16) % 256])),
    )
    con.execute(
        "INSERT INTO embedding_metadata(id,key,string_value) VALUES(?,?,?)",
        (rid, "chroma:document", text),
    )
    con.execute(
        "INSERT INTO embedding_metadata(id,key,string_value) VALUES(?,?,?)",
        (rid, "chunk_id", eid),
    )
    for k, v in meta.items():
        if isinstance(v, int) and not isinstance(v, bool):
            col, val = "int_value", v
        else:
            col, val = "string_value", str(v)
        con.execute(
            f"INSERT INTO embedding_metadata(id,key,{col}) VALUES(?,?,?)",
            (rid, k, val),
        )
    con.commit()
    con.close()


# --------------------------------------------------------------------------- #
# read_recoverable_chunks
# --------------------------------------------------------------------------- #
def test_read_recoverable_chunks_returns_only_dead_segment_chunks(tmp_path):
    db = tmp_path / "chroma.sqlite3"
    _build_chroma_sqlite(
        db,
        live_seg="LIVE",
        dead_seg="DEAD",
        live={"chunk_live": ("live text", {"source_type": "code"})},
        dead={"chunk_dead": ("dead text", {"source_type": "doc", "chunk_index": 3})},
    )
    got = read_recoverable_chunks(db, {"chunk_live", "chunk_dead", "chunk_absent"})

    # live-segment chunk excluded (still alive), absent chunk excluded
    assert set(got) == {"chunk_dead"}
    rc = got["chunk_dead"]
    assert rc.text == "dead text"
    assert rc.metadata["source_type"] == "doc"
    assert rc.metadata["chunk_index"] == 3  # typed int preserved
    assert "chroma:document" not in rc.metadata  # document split out of metadata


def test_read_recoverable_chunks_prefers_latest_dead_occurrence(tmp_path):
    # chunk_id is position-based (md5(source_idx)), so one id can have several
    # historical texts across stranded generations. Recovery must restore the
    # LATEST (highest embeddings.id = most recently indexed) content.
    db = tmp_path / "chroma.sqlite3"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE segments(id TEXT PRIMARY KEY, type TEXT NOT NULL,
            scope TEXT NOT NULL, collection TEXT NOT NULL);
        CREATE TABLE embeddings(id INTEGER PRIMARY KEY, segment_id TEXT NOT NULL,
            embedding_id TEXT NOT NULL, seq_id BLOB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(segment_id, embedding_id));
        CREATE TABLE embedding_metadata(id INTEGER, key TEXT NOT NULL,
            string_value TEXT, int_value INTEGER, float_value REAL,
            bool_value INTEGER, PRIMARY KEY(id, key));
        """
    )
    # same chunk_id in two dead segments; DEAD2 inserted later (higher id)
    for rid, (seg, text) in enumerate(
        [("DEAD1", "OLD content"), ("DEAD2", "NEW content")], start=1
    ):
        con.execute(
            "INSERT INTO embeddings(id,segment_id,embedding_id,seq_id) VALUES(?,?,?,?)",
            (rid, seg, "chunk_x", bytes([rid])),
        )
        con.execute(
            "INSERT INTO embedding_metadata(id,key,string_value) VALUES(?,?,?)",
            (rid, "chroma:document", text),
        )
    con.commit()
    con.close()

    got = read_recoverable_chunks(db, {"chunk_x"})
    assert got["chunk_x"].text == "NEW content"  # latest wins, not "OLD content"


# --------------------------------------------------------------------------- #
# load_cache_vectors
# --------------------------------------------------------------------------- #
def test_load_cache_vectors_matches_hash_and_dimensions(tmp_path):
    cache = tmp_path / "cache.db"
    _build_cache(
        cache,
        [
            ("hello", "OpenAI", "m", 4, [1.0, 2.0, 3.0, 4.0]),
            ("other", "OpenAI", "m", 8, [0.0] * 8),  # wrong dims
        ],
    )
    got = load_cache_vectors(
        cache,
        {_sha("hello"), _sha("other"), _sha("absent")},
        target_dimensions=4,
    )
    assert got[_sha("hello")] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert _sha("other") not in got  # dims 8 != 4 -> rejected
    assert _sha("absent") not in got


# --------------------------------------------------------------------------- #
# recover_lost_chunks (end-to-end, real collection)
# --------------------------------------------------------------------------- #
async def _seed_live(tmp_path):
    persist = str(tmp_path / "chroma_db")
    store = VectorStoreManager(persist_dir=persist, collection_name="testcol")
    await store.initialize()
    await store.upsert_documents(
        ids=["chunk_keep"],
        embeddings=[[9.0, 9.0, 9.0, 9.0]],
        documents=["keep"],
        metadatas=[{"source_type": "code"}],
    )
    await store.close()
    return persist


async def test_recover_restores_missing_chunk_with_cache_vector(tmp_path):
    persist = await _seed_live(tmp_path)
    chroma_db = Path(persist) / "chroma.sqlite3"
    _inject_dead_row(
        chroma_db,
        seg="DEAD",
        eid="chunk_lost",
        text="lost text",
        meta={"source_type": "doc", "chunk_index": 2},
    )
    cache = tmp_path / "cache.db"
    _build_cache(cache, [("lost text", "OpenAI", "m", 4, [5.0, 6.0, 7.0, 8.0])])

    store = VectorStoreManager(persist_dir=persist, collection_name="testcol")
    await store.initialize()
    summary = await recover_lost_chunks(
        vector_store=store,
        wanted_ids={"chunk_keep", "chunk_lost"},
        chroma_sqlite_path=chroma_db,
        cache_db_path=cache,
        target_dimensions=4,
        dry_run=False,
    )

    assert summary.wanted == 1
    assert summary.recoverable == 1
    assert summary.restored == 1
    assert summary.missed == 0
    assert summary.complete

    rec = store._collection.get(
        ids=["chunk_lost"], include=["documents", "metadatas", "embeddings"]
    )
    assert rec["documents"][0] == "lost text"
    assert rec["metadatas"][0]["source_type"] == "doc"
    # the restored vector is the CACHE vector verbatim — proof of no re-embed
    assert [round(x, 3) for x in rec["embeddings"][0]] == [5.0, 6.0, 7.0, 8.0]
    assert await store.get_count() == 2


async def test_recover_count_precheck_skips_probe_when_counts_match(tmp_path):
    # Fast path: when the store already holds exactly `len(wanted)` chunks, skip
    # the per-id probe entirely. Here the store has 1 chunk and the manifest
    # claims 1 (different) id; the count matches so recovery is a no-op.
    persist = await _seed_live(tmp_path)  # store has 1 chunk: chunk_keep
    store = VectorStoreManager(persist_dir=persist, collection_name="testcol")
    await store.initialize()
    summary = await recover_lost_chunks(
        vector_store=store,
        wanted_ids={"chunk_other"},  # 1 id, absent — but count (1) matches
        chroma_sqlite_path=Path(persist) / "chroma.sqlite3",
        cache_db_path=None,
        target_dimensions=4,
        dry_run=False,
    )
    assert summary.wanted == 0  # probe skipped by the count pre-check
    assert summary.complete


async def test_recover_dry_run_writes_nothing(tmp_path):
    persist = await _seed_live(tmp_path)
    chroma_db = Path(persist) / "chroma.sqlite3"
    _inject_dead_row(chroma_db, seg="DEAD", eid="chunk_lost", text="lost text", meta={})
    cache = tmp_path / "cache.db"
    _build_cache(cache, [("lost text", "OpenAI", "m", 4, [5.0, 6.0, 7.0, 8.0])])

    store = VectorStoreManager(persist_dir=persist, collection_name="testcol")
    await store.initialize()
    summary = await recover_lost_chunks(
        vector_store=store,
        wanted_ids={"chunk_keep", "chunk_lost"},
        chroma_sqlite_path=chroma_db,
        cache_db_path=cache,
        target_dimensions=4,
        dry_run=True,
    )
    assert summary.recoverable == 1
    assert summary.restored == 0
    assert not summary.complete  # dry-run never gates deep_clean open
    assert await store.get_count() == 1  # nothing written


async def test_recover_flags_unrecoverable_without_writing(tmp_path):
    persist = await _seed_live(tmp_path)
    chroma_db = Path(persist) / "chroma.sqlite3"
    # one missing chunk has dead text but NO cache vector
    _inject_dead_row(chroma_db, seg="DEAD", eid="chunk_textonly", text="t2", meta={})
    cache = tmp_path / "cache.db"
    _build_cache(cache, [("unrelated", "OpenAI", "m", 4, [0.0, 0.0, 0.0, 0.0])])

    store = VectorStoreManager(persist_dir=persist, collection_name="testcol")
    await store.initialize()
    summary = await recover_lost_chunks(
        vector_store=store,
        # chunk_notext is in manifest but neither dead nor cached
        wanted_ids={"chunk_keep", "chunk_textonly", "chunk_notext"},
        chroma_sqlite_path=chroma_db,
        cache_db_path=cache,
        target_dimensions=4,
        dry_run=False,
    )
    assert summary.wanted == 2
    assert summary.no_text == 1  # chunk_notext: nowhere
    assert summary.no_vector == 1  # chunk_textonly: text but no cache vector
    assert summary.recoverable == 0
    assert summary.restored == 0
    assert await store.get_count() == 1  # nothing written


# --------------------------------------------------------------------------- #
# RecoverySummary.complete — the deep_clean gate
# --------------------------------------------------------------------------- #
def test_summary_complete_gate_semantics():
    # every possible chunk restored, no error -> deep_clean may proceed
    assert RecoverySummary(wanted=3, recoverable=2, restored=2, missed=0).complete
    # missed a possible chunk -> blocked
    assert not RecoverySummary(wanted=3, recoverable=2, restored=1, missed=1).complete
    # error -> blocked
    assert not RecoverySummary(error="boom").complete
    # nothing was missing / nothing possible, no error -> proceed
    assert RecoverySummary(wanted=0, recoverable=0, restored=0).complete
    # dry-run is never "complete"
    assert not RecoverySummary(recoverable=2, restored=2, dry_run=True).complete


# --------------------------------------------------------------------------- #
# rebuild_bm25_from_collection (lexical rebuild, no external calls)
# --------------------------------------------------------------------------- #
class _FakeColl:
    def __init__(self, data):
        self._d = data

    def get(self, include=None):
        return self._d


class _FakeVS:
    def __init__(self, data):
        self._collection = _FakeColl(data)


class _FakeBM25:
    def __init__(self):
        self.built = None

    def build_index(self, nodes):
        self.built = list(nodes)


def test_rebuild_bm25_indexes_only_code_and_doc():
    # BM25 historically indexes only code/doc chunks; git_commit / session_turn
    # live in the same collection but must NOT enter the lexical index.
    data = {
        "ids": ["a", "b", "g", "s"],
        "documents": ["text a", "text b", "commit msg", "session turn"],
        "metadatas": [
            {"source_type": "code"},
            {"source_type": "doc"},
            {"source_type": "git_commit"},
            {"source_type": "session_turn"},
        ],
    }
    bm = _FakeBM25()
    n = rebuild_bm25_from_collection(bm, _FakeVS(data))
    assert n == 2
    assert {node.node_id for node in bm.built} == {"a", "b"}  # git/session excluded
    assert {node.get_content() for node in bm.built} == {"text a", "text b"}


def test_rebuild_bm25_noop_when_no_manager_or_store():
    assert rebuild_bm25_from_collection(None, _FakeVS({"ids": []})) == 0
    assert rebuild_bm25_from_collection(_FakeBM25(), None) == 0


# --------------------------------------------------------------------------- #
# detect_dimensions
# --------------------------------------------------------------------------- #
def test_detect_dimensions_from_cache_fingerprint(tmp_path):
    cache = tmp_path / "cache.db"
    con = sqlite3.connect(str(cache))
    con.execute(
        "CREATE TABLE embeddings(cache_key TEXT, embedding BLOB, provider TEXT, "
        "model TEXT, dimensions INTEGER, last_accessed REAL)"
    )
    con.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
    con.execute(
        "INSERT INTO metadata VALUES('provider_fingerprint',"
        "'openai:text-embedding-3-large:3072')"
    )
    con.commit()
    con.close()
    assert detect_dimensions(cache_db_path=cache) == 3072


def test_detect_dimensions_none_when_absent(tmp_path):
    assert detect_dimensions(cache_db_path=tmp_path / "nope.db") is None


# --------------------------------------------------------------------------- #
# self_heal_on_startup — recovery-first, deep_clean gated on full recovery
# --------------------------------------------------------------------------- #
import types  # noqa: E402

from brainpalace_server.services import startup_reconcile  # noqa: E402


async def _seed_manifest(tmp_path, chunk_ids):
    from brainpalace_server.services.folder_manager import FolderManager
    from brainpalace_server.services.manifest_tracker import (
        FileRecord,
        FolderManifest,
        ManifestTracker,
    )

    folder = str(tmp_path / "repo")
    fm = FolderManager(state_dir=tmp_path)
    await fm.initialize()
    await fm.add_folder(
        folder_path=folder,
        chunk_count=len(chunk_ids),
        chunk_ids=chunk_ids,
        watch_mode="auto",
        include_code=True,
    )
    mt = ManifestTracker(manifests_dir=tmp_path / "manifests")
    man = FolderManifest(folder_path=folder)
    man.files["f.py"] = FileRecord(checksum="x", mtime=1.0, chunk_ids=chunk_ids)
    await mt.save(man)
    return fm, mt


async def test_self_heal_runs_deep_clean_when_recovery_complete(monkeypatch, tmp_path):
    fm, mt = await _seed_manifest(tmp_path, ["chunk_a"])
    calls: list[str] = []

    async def fake_recover(**_):
        return RecoverySummary(wanted=1, recoverable=1, restored=1)

    async def fake_reconcile_folders(*_a, **_k):
        return None

    async def fake_deep_clean(*_a, **_k):
        calls.append("deep_clean")
        return startup_reconcile.DeepCleanSummary()

    monkeypatch.setattr(
        startup_reconcile.chunk_recovery, "recover_lost_chunks", fake_recover
    )
    monkeypatch.setattr(startup_reconcile, "reconcile_folders", fake_reconcile_folders)
    monkeypatch.setattr(startup_reconcile, "deep_clean", fake_deep_clean)

    report = await startup_reconcile.self_heal_on_startup(
        folder_manager=fm,
        manifest_tracker=mt,
        storage_backend=object(),
        vector_store=types.SimpleNamespace(persist_dir=str(tmp_path)),
        cache_db_path=None,
        target_dimensions=4,
    )
    assert report["deep_clean_ran"] is True
    assert calls == ["deep_clean"]


async def test_self_heal_skips_deep_clean_when_recovery_incomplete(
    monkeypatch, tmp_path
):
    fm, mt = await _seed_manifest(tmp_path, ["chunk_a", "chunk_b"])
    calls: list[str] = []

    async def fake_recover(**_):
        # missed a possible chunk -> recovery incomplete
        return RecoverySummary(wanted=2, recoverable=2, restored=1, missed=1)

    async def fake_reconcile_folders(*_a, **_k):
        return None

    async def fake_deep_clean(*_a, **_k):
        calls.append("deep_clean")
        return startup_reconcile.DeepCleanSummary()

    monkeypatch.setattr(
        startup_reconcile.chunk_recovery, "recover_lost_chunks", fake_recover
    )
    monkeypatch.setattr(startup_reconcile, "reconcile_folders", fake_reconcile_folders)
    monkeypatch.setattr(startup_reconcile, "deep_clean", fake_deep_clean)

    report = await startup_reconcile.self_heal_on_startup(
        folder_manager=fm,
        manifest_tracker=mt,
        storage_backend=object(),
        vector_store=types.SimpleNamespace(persist_dir=str(tmp_path)),
        cache_db_path=None,
        target_dimensions=4,
    )
    assert report["deep_clean_ran"] is False
    assert "incomplete" in (report["deep_clean_skipped_reason"] or "")
    assert calls == []  # destructive step must NOT run


async def test_self_heal_unions_git_ids_into_recovery(monkeypatch, tmp_path):
    # Git commits aren't manifest-tracked; self-heal must source their wanted ids
    # from the repo and union them into the recovery set.
    fm, mt = await _seed_manifest(tmp_path, ["chunk_a"])
    captured: dict = {}

    async def fake_recover(**kw):
        captured["wanted"] = set(kw["wanted_ids"])
        return RecoverySummary(wanted=0, recoverable=0, restored=0)

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(
        startup_reconcile.chunk_recovery, "recover_lost_chunks", fake_recover
    )
    monkeypatch.setattr(startup_reconcile, "reconcile_folders", noop)
    monkeypatch.setattr(startup_reconcile, "deep_clean", noop)
    monkeypatch.setattr(
        startup_reconcile, "_current_git_shas", lambda _p: {"sha1", "sha2"}
    )

    await startup_reconcile.self_heal_on_startup(
        folder_manager=fm,
        manifest_tracker=mt,
        storage_backend=object(),
        vector_store=types.SimpleNamespace(persist_dir=str(tmp_path)),
        cache_db_path=None,
        target_dimensions=4,
        repo_path="/repo",
    )
    assert "chunk_a" in captured["wanted"]  # manifest id
    assert "git_commit:sha1" in captured["wanted"]  # git ids unioned in
    assert "git_commit:sha2" in captured["wanted"]


async def test_self_heal_drops_unrecovered_files_and_enqueues_reindex(
    monkeypatch, tmp_path
):
    # File f.py has chunks c1,c2; after recovery only c1 is present -> f.py is
    # "not fully recovered" -> dropped from manifest -> reindex enqueued.
    fm, mt = await _seed_manifest(tmp_path, ["c1", "c2"])

    async def fake_recover(**_):
        return RecoverySummary(wanted=1, recoverable=1, restored=1)

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(
        startup_reconcile.chunk_recovery, "recover_lost_chunks", fake_recover
    )
    monkeypatch.setattr(startup_reconcile, "reconcile_folders", noop)
    monkeypatch.setattr(startup_reconcile, "deep_clean", noop)

    class FakeVS:
        persist_dir = "/x"

        async def get_existing_ids(self, ids):
            return {"c1"} & set(ids)  # c2 still missing

    class FakeJobs:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, **kw):
            self.calls.append(kw)
            return types.SimpleNamespace(dedupe_hit=False)

    jobs = FakeJobs()
    report = await startup_reconcile.self_heal_on_startup(
        folder_manager=fm,
        manifest_tracker=mt,
        storage_backend=object(),
        vector_store=FakeVS(),
        cache_db_path=None,
        target_dimensions=4,
        job_service=jobs,
    )
    assert report["files_dropped"] == 1
    assert report["reindex_enqueued"] == 1
    assert len(jobs.calls) == 1
    man = await mt.load(str(tmp_path / "repo"))
    assert man is None or "f.py" not in man.files  # dropped so it reindexes


def test_recovery_events_roundtrip(tmp_path):
    from brainpalace_server.services.chunk_recovery import (
        read_recovery_events,
        record_recovery_event,
    )

    persist = tmp_path / "data" / "chroma_db"
    persist.mkdir(parents=True)
    assert read_recovery_events(persist)["count"] == 0

    record_recovery_event(persist, {"restored": 5, "files_dropped": 2})
    record_recovery_event(persist, {"restored": 0, "error": "boom"})

    out = read_recovery_events(persist)
    assert out["count"] == 2
    assert out["last"]["error"] == "boom"
    assert "ts" in out["last"]
    assert (tmp_path / "recovery-events.jsonl").exists()  # at <state_dir> root


def test_recovery_events_path_none_for_legacy_layout(tmp_path):
    from brainpalace_server.services.chunk_recovery import read_recovery_events

    # persist_dir not under a 'data' parent -> no marker, no crash
    assert read_recovery_events(tmp_path / "chroma_db")["count"] == 0
