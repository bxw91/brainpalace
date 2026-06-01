# Session Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make session indexing read from a durable, user-curatable raw archive under `.brainpalace/session_archive/` instead of the live `~/.claude` transcripts, so sessions survive Claude Code removal/auto-delete and can be deleted by the user without resurrection.

**Architecture:** Insert a sync layer (`SessionArchiveService`) between the existing live `SessionWatcher` and `SessionIndexService`. On a live change, copy the raw transcript verbatim into a dated archive folder, then index the archive copy. A second watcher (`SessionArchiveWatcher`) watches the archive for deletions and purges the corresponding index chunks + writes a tombstone so the live source is never re-synced. `~/.claude` becomes read-only.

**Tech Stack:** Python 3.12, FastAPI lifespan wiring, `watchfiles.awatch`, `anyio`, pytest + pytest-asyncio, ChromaDB metadata filters (`delete_by_metadata`).

**Spec:** `docs/superpowers/specs/2026-06-01-session-archive-design.md`

## Execution strategy (decided)

**Inline, sequential, three human checkpoints.** Run all 12 tasks in order in a
single session (tasks have hard dependencies — no parallelism). Tests carry most
of the verification; the human reviews at only three moments:

1. **After Task 8** — deletion / purge logic (data-loss path).
2. **After Task 9** — real server boot smoke (`import brainpalace_server.api.main`
   + a real `brainpalace start` on a scratch project); lifespan wiring isn't
   covered by the fake-backed tests.
3. **Final gate** — full server + cli suites, ruff, mypy, and a real-project
   smoke: enable sessions, watch `.brainpalace/session_archive/<date>/` fill,
   delete a dated folder, confirm chunks drop and the session is not re-synced.

Everything between checkpoints rides on the task tests. Not test-covered (verify
by hand at the checkpoints): real Claude JSONL schema vs the synthetic fixtures,
live `watchfiles.awatch` deletion events, real ChromaDB/embedding integration,
and the privacy posture of full raw prompts on disk.

Use `superpowers:executing-plans` to run it.

**Test runner note (this repo/env):** a bogus `VIRTUAL_ENV=/usr` may hijack Poetry. Run tests via the in-project venv:
`cd brainpalace-server && unset VIRTUAL_ENV && .venv/bin/python -m pytest <args>`

---

## File Structure

**Create:**
- `brainpalace-server/brainpalace_server/services/session_archive_service.py` — sync raw transcript → archive, manifest + tombstone state, stats, backfill, reconcile-deletions. No indexing, no watching.
- `brainpalace-server/brainpalace_server/services/session_archive_watcher.py` — watch the archive dir for deletions → reconcile → purge index chunks.
- `brainpalace-server/tests/services/test_session_archive_service.py`
- `brainpalace-server/tests/services/test_session_archive_watcher.py`

**Modify:**
- `brainpalace_server/config/session_config.py` — add nested `archive` block.
- `brainpalace_server/indexing/session_loader.py` — add `origin_path` to `SessionMeta`.
- `brainpalace_server/indexing/session_chunker.py` — emit `origin_path` in chunk metadata.
- `brainpalace_server/services/session_index_service.py` — `index_session_file` accepts `origin_path`.
- `brainpalace_server/services/session_watcher.py` — sync to archive, index the archive path.
- `brainpalace_server/api/main.py` — wire archive service + backfill + archive watcher into lifespan.
- `brainpalace_server/api/routers/health.py` — add archive counts to `session_memory`.
- `brainpalace_cli/brainpalace_cli/commands/reset.py` — `--include-sessions` flag (archive preserved by default).
- `docs/SESSION_INDEXING.md` — privacy + archive section.

---

## Task 1: Config — add the `archive` block

**Files:**
- Modify: `brainpalace_server/config/session_config.py`
- Test: `brainpalace-server/tests/config/test_session_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_session_config.py
from brainpalace_server.config.session_config import SessionIndexingConfig


def test_archive_defaults_on_when_sessions_enabled() -> None:
    cfg = SessionIndexingConfig(enabled=True)
    assert cfg.archive.enabled is True
    assert cfg.archive.dir == ".brainpalace/session_archive"


def test_archive_block_overrides_parse() -> None:
    cfg = SessionIndexingConfig(
        enabled=True, archive={"enabled": False, "dir": "/custom/arch"}
    )
    assert cfg.archive.enabled is False
    assert cfg.archive.dir == "/custom/arch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/config/test_session_config.py -v`
Expected: FAIL — `SessionIndexingConfig` has no attribute `archive`.

- [ ] **Step 3: Implement the nested model**

In `session_config.py`, add above `SessionIndexingConfig`:

```python
class SessionArchiveConfig(BaseModel):
    """Raw-transcript archive settings (durable, user-curatable copies)."""

    enabled: bool = Field(
        default=True,
        description="Archive raw transcripts under .brainpalace/ and index the copy.",
    )
    dir: str = Field(
        default=".brainpalace/session_archive",
        description="Archive directory (relative to project root or absolute).",
    )
```

Add the field to `SessionIndexingConfig` (after `stride`):

```python
    archive: SessionArchiveConfig = Field(default_factory=SessionArchiveConfig)
```

The existing `load_session_indexing_config` filters block keys by
`SessionIndexingConfig.model_fields`, so `archive` passes through as a dict and
pydantic coerces it into `SessionArchiveConfig` automatically.

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/config/test_session_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/config/session_config.py brainpalace-server/tests/config/test_session_config.py
git commit -m "feat(sessions): add session_indexing.archive config block"
```

---

## Task 2: `SessionArchiveService` — manifest + tombstone state

The service persists two JSON files in the archive dir. This task builds only
the state layer (load/save/query); copying comes in Task 3.

**Files:**
- Create: `brainpalace_server/services/session_archive_service.py`
- Test: `brainpalace-server/tests/services/test_session_archive_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_session_archive_service.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the state layer**

```python
# brainpalace_server/services/session_archive_service.py
"""Durable raw-transcript archive for session indexing.

Copies live Claude transcripts (~/.claude/projects/<enc>/*.jsonl) verbatim into
a gitignored, dated archive under .brainpalace/, maintains a manifest and
tombstones, and is the source the index reads from. ~/.claude is read-only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionArchiveService:
    """File + state layer for the raw session archive (no indexing here)."""

    def __init__(self, archive_dir: str | Path) -> None:
        self.archive_dir = Path(archive_dir)
        self._manifest_path = self.archive_dir / "manifest.json"
        self._tombstone_path = self.archive_dir / "tombstones.json"
        self._manifest: dict[str, dict[str, Any]] = self._load(self._manifest_path)
        self._tombstones: dict[str, dict[str, Any]] = self._load(self._tombstone_path)

    @staticmethod
    def _load(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Archive state %s unreadable, treating as empty: %s",
                           path.name, exc)
            return {}

    def _save(self, path: Path, data: dict[str, dict[str, Any]]) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    # --- tombstones ---
    def is_tombstoned(self, session_id: str) -> bool:
        return session_id in self._tombstones

    def tombstone(self, session_id: str, origin_path: str) -> None:
        from datetime import datetime, timezone

        self._tombstones[session_id] = {
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "origin_path": origin_path,
        }
        self._save(self._tombstone_path, self._tombstones)

    # --- manifest ---
    def manifest_entry(self, session_id: str) -> dict[str, Any] | None:
        return self._manifest.get(session_id)

    def _put_manifest(self, session_id: str, entry: dict[str, Any]) -> None:
        self._manifest[session_id] = entry
        self._save(self._manifest_path, self._manifest)

    def _drop_manifest(self, session_id: str) -> None:
        if session_id in self._manifest:
            del self._manifest[session_id]
            self._save(self._manifest_path, self._manifest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_archive_service.py brainpalace-server/tests/services/test_session_archive_service.py
git commit -m "feat(sessions): SessionArchiveService manifest + tombstone state"
```

---

## Task 3: `SessionArchiveService.sync()` — copy live → archive

Copies a transcript verbatim into `<archive>/<YYYY-MM-DD>/<session_id>.jsonl`,
dated by `started_at`. Skips tombstoned sessions and unchanged files (mtime+size).
Subagent transcripts go under the parent's dated folder, preserving the
`subagents/` structure.

**Files:**
- Modify: `brainpalace_server/services/session_archive_service.py`
- Test: `brainpalace-server/tests/services/test_session_archive_service.py`

- [ ] **Step 1: Write the failing tests**

```python
import json as _json


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
    assert archive_path == tmp_path / "arch" / "2026-06-01" / "s_abc.jsonl"
    assert archive_path.read_text() == live.read_text()  # verbatim
    assert svc.manifest_entry("s_abc")["origin_path"] == str(live)


def test_sync_skips_tombstoned(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s_x.jsonl"
    _write_transcript(live, "s_x", "2026-06-01T10:00:00Z")
    svc = SessionArchiveService(archive_dir=tmp_path / "arch")
    svc.tombstone("s_x", origin_path=str(live))

    assert svc.sync(live) is None
    assert not (tmp_path / "arch" / "2026-06-01" / "s_x.jsonl").exists()


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
        f.write(_json.dumps({"sessionId": "s_z", "timestamp": "2026-06-05T09:00:00Z",
                             "type": "assistant",
                             "message": {"role": "assistant",
                                         "content": [{"type": "text", "text": "more"}]}}) + "\n")
    again = svc.sync(live)
    assert again == archive_path  # same file, original started_at date
    assert again.read_text() == live.read_text()  # overwritten with full content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -k sync -v`
Expected: FAIL — `sync` not defined.

- [ ] **Step 3: Implement `sync()` and helpers**

Add imports at top of `session_archive_service.py`:

```python
import shutil

from brainpalace_server.indexing.session_loader import (
    is_subagent_path,
    load_session,
    parent_session_id_for,
)
```

Add methods to `SessionArchiveService`:

```python
    @staticmethod
    def _date_for(started_at: str | None) -> str:
        # ISO timestamps start "YYYY-MM-DD"; fall back to a stable bucket.
        if started_at and len(started_at) >= 10 and started_at[4] == "-":
            return started_at[:10]
        return "undated"

    def _dest_for(self, live_path: Path, session_id: str, date: str) -> Path:
        """Archive destination, preserving subagent structure under parent date."""
        if is_subagent_path(live_path):
            parent_id = parent_session_id_for(live_path) or "unknown-parent"
            parent_entry = self.manifest_entry(parent_id)
            parent_date = parent_entry["archived_date"] if parent_entry else date
            return (self.archive_dir / parent_date / parent_id / "subagents"
                    / live_path.name)
        return self.archive_dir / date / f"{session_id}.jsonl"

    def sync(self, live_path: str | Path) -> Path | None:
        """Copy a live transcript into the archive. Returns archive path or None.

        None when the session is tombstoned (curated away) or unchanged.
        """
        live_path = Path(live_path)
        try:
            meta, _turns = load_session(live_path)
        except (OSError, ValueError) as exc:
            logger.warning("Cannot read transcript %s: %s", live_path, exc)
            return None
        session_id = meta.session_id or live_path.stem

        if self.is_tombstoned(session_id):
            return None

        try:
            stat = live_path.stat()
        except OSError:
            return None

        entry = self.manifest_entry(session_id)
        if (entry and entry.get("src_mtime") == stat.st_mtime
                and entry.get("src_size") == stat.st_size):
            return Path(entry["archive_path"])  # unchanged: no re-copy

        date = self._date_for(meta.started_at)
        dest = self._dest_for(live_path, session_id, date)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_path, dest)  # copy2 preserves mtime

        self._put_manifest(session_id, {
            "origin_path": str(live_path),
            "archive_path": str(dest),
            "archived_date": date,
            "src_mtime": stat.st_mtime,
            "src_size": stat.st_size,
        })
        return dest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -k sync -v`
Expected: PASS (4 sync tests + resume).

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_archive_service.py brainpalace-server/tests/services/test_session_archive_service.py
git commit -m "feat(sessions): archive sync (dated, tombstone-skip, mtime no-op, resume overwrite)"
```

---

## Task 4: `reconcile_deletions()` — detect curated-away sessions

When the user deletes an archive file/folder, every manifest entry whose
`archive_path` no longer exists is a deletion: return its `session_id`, write a
tombstone, and drop the manifest entry. The caller purges the index.

**Files:**
- Modify: `brainpalace_server/services/session_archive_service.py`
- Test: `brainpalace-server/tests/services/test_session_archive_service.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -k reconcile -v`
Expected: FAIL — `reconcile_deletions` not defined.

- [ ] **Step 3: Implement `reconcile_deletions()`**

```python
    def reconcile_deletions(self) -> list[str]:
        """Tombstone + drop manifest entries whose archive file is gone.

        Returns the session_ids removed (so the caller can purge index chunks).
        """
        removed: list[str] = []
        for session_id, entry in list(self._manifest.items()):
            archive_path = Path(entry.get("archive_path", ""))
            if not archive_path.exists():
                removed.append(session_id)
                self.tombstone(session_id, origin_path=entry.get("origin_path", ""))
                self._drop_manifest(session_id)
        return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -k reconcile -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_archive_service.py brainpalace-server/tests/services/test_session_archive_service.py
git commit -m "feat(sessions): reconcile_deletions tombstones curated-away sessions"
```

---

## Task 5: `stats()` and `backfill()`

`stats()` feeds `brainpalace status`. `backfill()` syncs a batch of live paths
(used once at startup), returning the archive paths produced.

**Files:**
- Modify: `brainpalace_server/services/session_archive_service.py`
- Test: `brainpalace-server/tests/services/test_session_archive_service.py`

- [ ] **Step 1: Write the failing test**

```python
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
    # Second run: unchanged → still returns the archive paths, no errors.
    again = svc.backfill(paths)
    assert sorted(map(str, again)) == sorted(map(str, produced))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -k "stats or backfill" -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement `stats()` and `backfill()`**

```python
    from collections.abc import Iterable  # add to top-of-file imports

    def stats(self) -> dict[str, Any]:
        archived_bytes = 0
        for entry in self._manifest.values():
            p = Path(entry.get("archive_path", ""))
            if p.exists():
                archived_bytes += p.stat().st_size
        return {
            "archived_sessions": len(self._manifest),
            "tombstoned": len(self._tombstones),
            "archived_bytes": archived_bytes,
        }

    def backfill(self, live_paths: "Iterable[str | Path]") -> list[Path]:
        produced: list[Path] = []
        for live in live_paths:
            archive_path = self.sync(live)
            if archive_path is not None:
                produced.append(archive_path)
        return produced
```

Move the `Iterable` import to the top with the other imports (don't leave it
inside the class body); shown inline here only to mark where it's used.

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_service.py -v`
Expected: PASS (all service tests).

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_archive_service.py brainpalace-server/tests/services/test_session_archive_service.py
git commit -m "feat(sessions): archive stats + backfill"
```

---

## Task 6: Thread `origin_path` through meta → chunker → index

So index chunks record provenance: `source_path` = archive path (already, since
we load the archive), plus `origin_path` = the live `~/.claude` path.

**Files:**
- Modify: `brainpalace_server/indexing/session_loader.py` (SessionMeta)
- Modify: `brainpalace_server/indexing/session_chunker.py` (metadata)
- Modify: `brainpalace_server/services/session_index_service.py` (param)
- Test: `brainpalace-server/tests/indexing/test_session_chunker.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/indexing/test_session_chunker.py`:

```python
def test_chunk_metadata_includes_origin_path() -> None:
    from brainpalace_server.indexing.session_chunker import SessionChunker
    from brainpalace_server.indexing.session_loader import SessionMeta, Turn

    meta = SessionMeta(
        session_id="s1", project_path="/p", branch=None,
        started_at="2026-06-01T10:00:00Z", ended_at=None,
        source_path="/arch/2026-06-01/s1.jsonl",
        origin_path="/home/u/.claude/projects/p/s1.jsonl",
    )
    turns = [Turn(index=0, role="assistant", kind="text", text="hello world")]
    chunks = SessionChunker(window=1, stride=1).chunk(meta, turns)
    assert chunks, "expected at least one chunk"
    md = chunks[0].metadata.to_dict()
    assert md["origin_path"] == "/home/u/.claude/projects/p/s1.jsonl"
    assert md["source_path"] == "/arch/2026-06-01/s1.jsonl"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/indexing/test_session_chunker.py::test_chunk_metadata_includes_origin_path -v`
Expected: FAIL — `SessionMeta` has no `origin_path` (TypeError).

- [ ] **Step 3: Implement the field + metadata**

In `session_loader.py`, add to the `SessionMeta` dataclass (after `parent_session_id`):

```python
    origin_path: str | None = None
```

In `session_chunker.py`, in the metadata dict (next to `"source_path": meta.source_path,`):

```python
                "origin_path": meta.origin_path,
```

The existing None-drop in the chunker (it already strips keys like
`parent_session_id`, `started_at` when None) covers `origin_path` when unset —
confirm `origin_path` is included in that drop set; if the drop is an explicit
list of keys, add `"origin_path"` to it.

In `session_index_service.py`, change `index_session_file` to accept and apply
`origin_path`:

```python
    async def index_session_file(
        self,
        path: str | Path,
        include_user_turns: bool = False,
        window: int = 4,
        stride: int = 2,
        origin_path: str | None = None,
    ) -> dict[str, Any]:
        """Chunk + dedup + embed + upsert a single transcript."""
        meta, turns = load_session(path)
        if origin_path is not None:
            meta.origin_path = origin_path
        chunker = SessionChunker(
            window=window, stride=stride, include_user_turns=include_user_turns
        )
        chunks = chunker.chunk(meta, turns)
        # ... rest unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/indexing/test_session_chunker.py -v`
Expected: PASS (new test + existing chunker tests still green).

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/indexing/session_loader.py brainpalace-server/brainpalace_server/indexing/session_chunker.py brainpalace-server/brainpalace_server/services/session_index_service.py brainpalace-server/tests/indexing/test_session_chunker.py
git commit -m "feat(sessions): record origin_path (live source) in chunk metadata"
```

---

## Task 7: Wire archive into `SessionWatcher`

On a live change, sync to the archive and index the archive path (not the live
path). If sync returns None (tombstoned/unreadable), skip indexing.

**Files:**
- Modify: `brainpalace_server/services/session_watcher.py`
- Test: `brainpalace-server/tests/services/test_session_watcher.py` (create/extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_session_watcher.py
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_watcher import SessionWatcher


def _write_transcript(path: Path, sid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "sessionId": sid, "timestamp": "2026-06-01T10:00:00Z", "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_ingest_syncs_then_indexes_archive_path(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write_transcript(live, "s1")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    service = AsyncMock()
    cfg = SessionIndexingConfig(enabled=True)

    watcher = SessionWatcher(tmp_path / "live", service, cfg, archive=archive)
    await watcher._ingest_paths({str(live)})

    service.index_session_file.assert_awaited_once()
    called_path = service.index_session_file.call_args.args[0]
    assert str(called_path).startswith(str(tmp_path / "arch"))  # archive, not live
    assert service.index_session_file.call_args.kwargs["origin_path"] == str(live)


@pytest.mark.asyncio
async def test_ingest_skips_tombstoned(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s2.jsonl"
    _write_transcript(live, "s2")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive.tombstone("s2", origin_path=str(live))
    service = AsyncMock()
    watcher = SessionWatcher(tmp_path / "live", service, SessionIndexingConfig(),
                             archive=archive)
    await watcher._ingest_paths({str(live)})
    service.index_session_file.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_watcher.py -v`
Expected: FAIL — `SessionWatcher.__init__` has no `archive` kwarg.

- [ ] **Step 3: Wire the archive in**

In `session_watcher.py`, extend `__init__` with an optional archive and use it
in `_ingest_paths`. Add to `__init__` params (after `config`):

```python
        archive: "SessionArchiveService | None" = None,
```
and in the body:
```python
        self.archive = archive
```
Add to the `TYPE_CHECKING` block:
```python
    from brainpalace_server.services.session_archive_service import (
        SessionArchiveService,
    )
```

Replace the per-path body of `_ingest_paths` (the part that calls
`self.service.index_session_file(...)`) with:

```python
            target = Path(path)
            origin_path: str | None = None
            if self.archive is not None:
                archived = self.archive.sync(path)
                if archived is None:
                    continue  # tombstoned / unreadable: do not index
                origin_path = str(path)
                target = archived
            try:
                await self.service.index_session_file(
                    target,
                    include_user_turns=self.config.include_user_turns,
                    window=self.config.window,
                    stride=self.config.stride,
                    origin_path=origin_path,
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Session ingest failed for %s: %s", target, exc)
```

(Keep the existing `.jsonl`/exists guards above this block. If the current code
passes other kwargs to `index_session_file`, preserve them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_watcher.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_watcher.py brainpalace-server/tests/services/test_session_watcher.py
git commit -m "feat(sessions): watcher syncs to archive then indexes the archive copy"
```

---

## Task 8: `SessionArchiveWatcher` — purge on deletion

Watches the archive dir; on any deletion event, calls
`archive.reconcile_deletions()` and purges each removed session's chunks from
the index via `delete_by_metadata`.

**Files:**
- Create: `brainpalace_server/services/session_archive_watcher.py`
- Test: `brainpalace-server/tests/services/test_session_archive_watcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_session_archive_watcher.py
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_archive_watcher import SessionArchiveWatcher


def _write(path: Path, sid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "sessionId": sid, "timestamp": "2026-06-01T10:00:00Z", "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_purge_deleted_removes_chunks(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write(live, "s1")
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    archive_path = archive.sync(live)
    storage = AsyncMock()
    storage.delete_by_metadata.return_value = 3

    watcher = SessionArchiveWatcher(tmp_path / "arch", archive, storage)
    archive_path.unlink()  # curated away
    purged = await watcher.purge_deleted()

    assert purged == ["s1"]
    storage.delete_by_metadata.assert_awaited_once_with(
        {"source_type": "session_turn", "session_id": "s1"}
    )
    assert archive.is_tombstoned("s1") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_watcher.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the watcher**

```python
# brainpalace_server/services/session_archive_watcher.py
"""Watch the session archive for deletions and purge the index accordingly.

Mirrors SessionWatcher's watchfiles pattern but reacts to *removals*: when the
user deletes an archived transcript/folder, reconcile the manifest, purge the
session's chunks (delete_by_metadata), and let the service tombstone it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import watchfiles

if TYPE_CHECKING:
    from brainpalace_server.services.session_archive_service import (
        SessionArchiveService,
    )

logger = logging.getLogger(__name__)


class SessionArchiveWatcher:
    """React to archive-file deletions by purging the corresponding chunks."""

    def __init__(
        self,
        archive_dir: str | Path,
        archive: SessionArchiveService,
        storage_backend: Any,
        debounce_ms: int = 1000,
    ) -> None:
        self.archive_dir = Path(archive_dir)
        self.archive = archive
        self.storage_backend = storage_backend
        self.debounce_ms = debounce_ms
        self._stop_event: anyio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._stop_event is not None and not self._stop_event.is_set()

    async def purge_deleted(self) -> list[str]:
        """Reconcile deletions and purge each removed session's chunks."""
        removed = self.archive.reconcile_deletions()
        for session_id in removed:
            try:
                await self.storage_backend.delete_by_metadata(
                    {"source_type": "session_turn", "session_id": session_id}
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Purge failed for session %s: %s", session_id, exc)
        return removed

    async def start(self) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event = anyio.Event()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        assert self._stop_event is not None
        try:
            async for _changes in watchfiles.awatch(
                self.archive_dir,
                stop_event=self._stop_event,  # type: ignore[arg-type]
                debounce=self.debounce_ms,
            ):
                await self.purge_deleted()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Archive watcher stopped: %s", exc)
```

(Match the exact `watchfiles.awatch` call signature used in
`session_watcher.py` — copy its `stop_event`/`debounce` argument style verbatim
to stay consistent with the installed `watchfiles` version.)

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/services/test_session_archive_watcher.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/services/session_archive_watcher.py brainpalace-server/tests/services/test_session_archive_watcher.py
git commit -m "feat(sessions): SessionArchiveWatcher purges chunks on archive deletion"
```

---

## Task 9: Lifespan wiring + backfill (main.py)

Instantiate the archive service when sessions + archive are enabled, backfill
existing transcripts, pass the archive to `SessionWatcher`, and start the
`SessionArchiveWatcher`. Store on `app.state` for status + shutdown.

**Files:**
- Modify: `brainpalace_server/api/main.py` (the session block ~629–676, and the
  shutdown block ~896)
- Test: `brainpalace-server/tests/integration/test_session_archive_e2e.py` (create)

- [ ] **Step 1: Write the failing E2E test**

```python
# tests/integration/test_session_archive_e2e.py
import json
from pathlib import Path

import pytest

from brainpalace_server.config.session_config import SessionIndexingConfig
from brainpalace_server.services.session_archive_service import SessionArchiveService
from brainpalace_server.services.session_index_service import SessionIndexService
from brainpalace_server.services.session_watcher import SessionWatcher
from brainpalace_server.services.session_archive_watcher import SessionArchiveWatcher


class _FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def get_by_id(self, cid: str):
        return self.docs.get(cid)

    async def upsert_documents(self, ids, embeddings, documents, metadatas):
        for cid, md in zip(ids, metadatas):
            self.docs[cid] = md

    async def delete_by_metadata(self, where: dict) -> int:
        sid = where["session_id"]
        gone = [c for c, md in self.docs.items() if md.get("session_id") == sid]
        for c in gone:
            del self.docs[c]
        return len(gone)


class _FakeEmbedder:
    async def embed_chunks(self, chunks):
        return [[0.0] for _ in chunks]


def _write(path: Path, sid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "sessionId": sid, "timestamp": "2026-06-01T10:00:00Z", "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    }) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_archive_index_then_delete_purges(tmp_path: Path) -> None:
    live = tmp_path / "live" / "s1.jsonl"
    _write(live, "s1")
    store = _FakeStore()
    archive = SessionArchiveService(archive_dir=tmp_path / "arch")
    index = SessionIndexService(_FakeEmbedder(), store)
    watcher = SessionWatcher(tmp_path / "live", index, SessionIndexingConfig(enabled=True),
                             archive=archive)

    await watcher._ingest_paths({str(live)})
    assert store.docs, "expected indexed chunks from the archive copy"
    assert all(md["source_path"].startswith(str(tmp_path / "arch"))
               for md in store.docs.values())

    # Curate away → archive deletion watcher purges.
    archive_path = Path(archive.manifest_entry("s1")["archive_path"])
    archive_path.unlink()
    del_watcher = SessionArchiveWatcher(tmp_path / "arch", archive, store)
    purged = await del_watcher.purge_deleted()
    assert purged == ["s1"]
    assert store.docs == {}
    # No resurrection on a later sync of the still-present live source.
    await watcher._ingest_paths({str(live)})
    assert store.docs == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/integration/test_session_archive_e2e.py -v`
Expected: PASS already IF Tasks 5–8 are merged (this is an integration check of
existing units). If it fails, fix the unit wiring before touching main.py.

- [ ] **Step 3: Wire into the lifespan**

In `main.py`, inside the `if session_cfg.enabled and app.state.project_root:`
block, after `sess_svc = SessionIndexService(...)` and before constructing the
watcher, add:

```python
                from pathlib import Path as _Path
                from brainpalace_server.services.session_archive_service import (
                    SessionArchiveService,
                )
                from brainpalace_server.services.session_archive_watcher import (
                    SessionArchiveWatcher,
                )

                archive_service = None
                archive_watcher = None
                if session_cfg.archive.enabled:
                    arch_dir = _Path(session_cfg.archive.dir)
                    if not arch_dir.is_absolute():
                        arch_dir = _Path(app.state.project_root) / arch_dir
                    archive_service = SessionArchiveService(archive_dir=arch_dir)
                app.state.session_archive_service = archive_service
```

Change the boot-index coroutine to backfill the archive first, then index from
it (replace the body of `_boot_session_index`):

```python
                async def _boot_session_index() -> None:
                    try:
                        if archive_service is not None:
                            live_files = sess_svc._discover(sessions_dir)
                            archive_service.backfill(live_files)
                        summary = await sess_svc.index_project(
                            app.state.project_root, session_cfg
                        )
                        logger.info("Session boot-index: %d file(s)",
                                    summary.get("files", 0))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Session boot-index failed: %s", exc)
```

Pass the archive to the live watcher:

```python
                watcher = SessionWatcher(
                    sessions_dir, sess_svc, session_cfg, archive=archive_service
                )
                await watcher.start()
                app.state.session_watcher = watcher

                if archive_service is not None:
                    archive_watcher = SessionArchiveWatcher(
                        archive_service.archive_dir, archive_service, storage_backend
                    )
                    await archive_watcher.start()
                app.state.session_archive_watcher = archive_watcher
```

Initialize the new state defaults near the other `app.state.session_* = None`:

```python
        app.state.session_archive_service = None
        app.state.session_archive_watcher = None
```

In the shutdown block (near `session_watcher.stop()`), add:

```python
    archive_watcher = getattr(app.state, "session_archive_watcher", None)
    if archive_watcher is not None:
        try:
            await archive_watcher.stop()
        except Exception:  # noqa: BLE001
            pass
```

NOTE on `index_project`: it indexes live paths from `_discover`. With the
archive enabled, the boot path should index the **archive** copies. Minimal
change: after `backfill`, the live `SessionWatcher` already re-indexes via the
archive on file events; for the boot pass, iterate the backfilled archive paths
and call `sess_svc.index_session_file(archive_path, origin_path=<live>)`
directly instead of `index_project`. Implement the boot loop as:

```python
                        if archive_service is not None:
                            live_files = sess_svc._discover(sessions_dir)
                            cutoff = time.time() - session_cfg.retain_days * 86400
                            for live in live_files:
                                try:
                                    if live.stat().st_mtime < cutoff:
                                        continue
                                except OSError:
                                    continue
                                arch = archive_service.sync(live)
                                if arch is None:
                                    continue
                                await sess_svc.index_session_file(
                                    arch,
                                    include_user_turns=session_cfg.include_user_turns,
                                    window=session_cfg.window,
                                    stride=session_cfg.stride,
                                    origin_path=str(live),
                                )
                        else:
                            await sess_svc.index_project(
                                app.state.project_root, session_cfg
                            )
```

(`time` is already imported in main.py; if not, add `import time`.)

- [ ] **Step 4: Run the full session + integration suite**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/integration/test_session_archive_e2e.py tests/services/test_session_watcher.py -v`
Expected: PASS. Then a smoke import: `unset VIRTUAL_ENV && .venv/bin/python -c "import brainpalace_server.api.main"` — no errors.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/api/main.py brainpalace-server/tests/integration/test_session_archive_e2e.py
git commit -m "feat(sessions): wire archive service + backfill + deletion watcher into lifespan"
```

---

## Task 10: Status — expose archive counts

Add `archived_sessions`, `archived_bytes`, `tombstoned` to the `session_memory`
status payload.

**Files:**
- Modify: `brainpalace_server/api/routers/health.py` (the `session_memory` dict ~293)
- Test: `brainpalace-server/tests/unit/test_runtime_endpoint.py` or the health test (extend)

- [ ] **Step 1: Write the failing test**

Add to the health/status test module:

```python
def test_session_memory_includes_archive_counts(monkeypatch) -> None:
    # Build a minimal app.state stand-in with an archive service.
    class _Arch:
        def stats(self):
            return {"archived_sessions": 2, "archived_bytes": 1234, "tombstoned": 1}

    # The test should call the status assembly with app.state.session_archive_service
    # set to _Arch() and assert the three keys appear under session_memory.
    # (Use the existing status-building helper/route test harness in this file.)
```

Implement this against the existing status-route test harness in the file
(follow the pattern already used for `session_chunks`). Assert
`payload["session_memory"]["archived_sessions"] == 2`,
`["archived_bytes"] == 1234`, `["tombstoned"] == 1`.

- [ ] **Step 2: Run test to verify it fails**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/unit/test_runtime_endpoint.py -k session_memory -v`
Expected: FAIL — keys absent.

- [ ] **Step 3: Implement**

In `health.py`, where `session_memory` is assembled, after `session_chunks`:

```python
    archive_service = getattr(request.app.state, "session_archive_service", None)
    archive_stats = (
        archive_service.stats()
        if archive_service is not None
        else {"archived_sessions": 0, "archived_bytes": 0, "tombstoned": 0}
    )
```
and merge into the `session_memory` dict:
```python
        "archived_sessions": int(archive_stats["archived_sessions"]),
        "archived_bytes": int(archive_stats["archived_bytes"]),
        "tombstoned": int(archive_stats["tombstoned"]),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/unit/test_runtime_endpoint.py -k session_memory -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-server/brainpalace_server/api/routers/health.py brainpalace-server/tests/unit/test_runtime_endpoint.py
git commit -m "feat(sessions): status reports archive counts (sessions/bytes/tombstoned)"
```

---

## Task 11: `reset --include-sessions` (archive preserved by default)

Plain `brainpalace reset` clears the index but never the archive. A new
`--include-sessions` flag opts into deleting `session_archive/`.

**Files:**
- Modify: `brainpalace_cli/brainpalace_cli/commands/reset.py`
- Test: `brainpalace-cli/tests/test_reset.py` (create/extend)

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-cli/tests/test_reset.py
from click.testing import CliRunner

from brainpalace_cli.commands.reset import reset_command  # adjust import to actual name


def test_reset_has_include_sessions_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(reset_command, ["--help"])
    assert result.exit_code == 0
    assert "--include-sessions" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/user/VSCode-projects-public/brainpalace/brainpalace-cli && unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/test_reset.py -v`
Expected: FAIL — flag/import missing. (First open `reset.py` to confirm the
command's actual symbol + how it locates the state dir; adjust the import and
deletion path accordingly.)

- [ ] **Step 3: Implement the flag**

In `reset.py`, add the option and, when set, delete the archive dir
(`<state_dir>/session_archive` or the configured `session_indexing.archive.dir`):

```python
@click.option(
    "--include-sessions",
    is_flag=True,
    default=False,
    help="Also delete the raw session archive (.brainpalace/session_archive). "
         "Off by default — the archive survives a normal reset.",
)
```
In the body, only when `include_sessions` is true:
```python
    if include_sessions:
        import shutil
        archive_dir = state_dir / "session_archive"
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
            console.print(f"[yellow]Deleted session archive:[/] {archive_dir}")
    else:
        console.print("[dim]Session archive preserved (use --include-sessions to "
                      "delete it).[/]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd brainpalace-cli && unset VIRTUAL_ENV && .venv/bin/python -m pytest tests/test_reset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-cli/brainpalace_cli/commands/reset.py brainpalace-cli/tests/test_reset.py
git commit -m "feat(cli): reset --include-sessions; archive preserved by default"
```

---

## Task 12: Docs — privacy + archive section

**Files:**
- Modify: `docs/SESSION_INDEXING.md`

- [ ] **Step 1: Add an "Archive & durability" section**

Document: archive location (`.brainpalace/session_archive/<YYYY-MM-DD>/<id>.jsonl`),
that it is the **full raw transcript** (user turns included regardless of
`include_user_turns`, which only filters the index), curation by filesystem
deletion (+ tombstone, no resurrection), `~/.claude` is read-only, `retain_days`
gates indexing only (archive kept forever), and that `brainpalace reset`
preserves the archive unless `--include-sessions` is passed. Include the config
block:

```yaml
session_indexing:
  enabled: true
  archive:
    enabled: true
    dir: .brainpalace/session_archive
  include_user_turns: false   # indexing filter only — archive is always full raw
  retain_days: 90             # gates indexing; archive kept forever
```

- [ ] **Step 2: Verify the doc renders / no broken frontmatter**

Run: `unset VIRTUAL_ENV && python3 scripts/lint_yaml_frontmatter.py brainpalace-plugin/` (sanity; SESSION_INDEXING.md has no frontmatter to break) and re-read the section.

- [ ] **Step 3: Commit**

```bash
git add docs/SESSION_INDEXING.md
git commit -m "docs: session archive — durability, curation, privacy, reset semantics"
```

---

## Final gate

- [ ] **Run the full server + cli suites and quality gate**

```bash
cd /home/user/VSCode-projects-public/brainpalace/brainpalace-server && unset VIRTUAL_ENV && .venv/bin/python -m pytest tests -q
cd /home/user/VSCode-projects-public/brainpalace/brainpalace-cli && unset VIRTUAL_ENV && .venv/bin/python -m pytest tests -q
cd /home/user/VSCode-projects-public/brainpalace && unset VIRTUAL_ENV && \
  brainpalace-server/.venv/bin/python -m ruff check brainpalace-server/brainpalace_server brainpalace-cli/brainpalace_cli && \
  brainpalace-server/.venv/bin/python -m mypy brainpalace-server/brainpalace_server
```
Expected: all green. Fix per-stage failures before finishing.

- [ ] **Manual smoke (optional, real server):** enable sessions on a scratch
  project, start the server, confirm `.brainpalace/session_archive/<date>/` fills
  with `.jsonl` copies, `brainpalace status` shows archive counts, delete a dated
  folder, confirm chunks drop and the session is not re-synced.

---

## Notes / invariants for the implementer

- **`~/.claude` is read-only.** Only `load_session`/`stat`/`copy2` (read side)
  ever touch it. Never write or delete there.
- **Manifest key = each transcript's own `session_id`** (top-level and subagent
  files each get an entry). `reconcile_deletions` purges by `session_id`.
- **Tombstone wins races:** a tombstoned session is never re-synced even if a
  later live change event arrives.
- **Backfill is idempotent** via the manifest (mtime/size no-op).
- **`source_path` = archive path; `origin_path` = live path.** Dedup + purge key
  off `session_id`, so changing `source_path` to the archive path is safe.
