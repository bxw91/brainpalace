# Session Archive — durable, curatable raw session indexing

**Created:** 2026-06-01
**Status:** Approved design (brainstorming) — ready for implementation plan
**Subsystem:** `brainpalace-server` session indexing

## Goals

Replace live-only session indexing with an archive-backed model that delivers
three things:

- **(a) Durability** — raw session transcripts survive Claude Code removal and
  Claude's own transcript auto-delete/rotation.
- **(b) Curation** — the user decides which sessions to keep or delete, via the
  filesystem, and deletion sticks (no resurrection).
- **(c) Source independence** — `~/.claude/projects/<encoded>/` becomes a
  strictly **read-only data source**. All indexing reads from the archive copy,
  never the live transcript.

## Non-goals (v1, YAGNI)

- `sessions list/rm/restore` CLI commands — the filesystem is the curation UI.
- Archive compression, cross-machine archive sync.
- Changing the session-aware chunking algorithm (window/stride, tool/role
  extraction, subagent linking) — reused unchanged.

## Background (current state)

- `SessionWatcher` (`services/session_watcher.py`) watches
  `~/.claude/projects/<encoded>/*.jsonl` with `watchfiles.awatch`; on change it
  calls `SessionIndexService.index_session_file(live_path)`. Deliberately NOT
  routed through `FileWatcherService` (which is bound to the code/doc folder +
  job-queue pipeline and would mishandle JSONL).
- `indexing/session_loader.py` parses JSONL → `SessionMeta` + `Turn`s; helpers
  `is_subagent_path` / `parent_session_id_for` derive subagent structure from
  the path (`.../<parent-session-id>/subagents/agent-*.jsonl`).
- `indexing/session_chunker.py` builds session-aware chunks
  (`role_mix`, `tools_used`, `files_touched`, `parent_session_id`, …). **No LLM**
  — embeddings only, via the embedding provider. Summaries/decisions/triplets
  come from the agent (extract-session), not a server-side summarization API.
- `config/session_config.py` holds `enabled`, `include_user_turns`,
  `retain_days`, `window`, `stride`, `sessions_dir`.

The index currently stores `source_path` = the live `~/.claude` path. If that
source is deleted, the raw transcript is unrecoverable.

## Approach (chosen: A — sync layer inside the session pipeline)

Insert an archive/sync layer between source discovery and indexing. The session
chunker and the live watcher's real-time behavior are preserved. Two watchers:
the existing one for additions/changes on the **live** dir, a new one for
**deletions** on the **archive** dir.

Rejected alternatives:
- **B (route archive through generic doc folder + FileWatcherService):** the
  generic doc chunker mangles JSONL and loses role/tool/subagent structure.
- **C (cron/scan sync, no live watcher):** regresses the real-time latency the
  system already has.

## Components

### New

- **`SessionArchiveService`** (`services/session_archive_service.py`)
  Pure file + state logic, no indexing. Responsibilities:
  - `sync(live_path) -> archive_path | None` — copy a live transcript verbatim
    into the archive (overwrite-on-change); sync its `subagents/`; update the
    manifest. Returns `None` (skips) when the session is tombstoned or unchanged.
  - manifest + tombstone read/write.
  - `backfill()` — one-time sync of all existing live transcripts.
- **`SessionArchiveWatcher`** (`services/session_archive_watcher.py`)
  Watches the archive dir for **deletions only**. On a deleted
  `<session_id>.jsonl` (or dated folder): purge that session's chunks from the
  index, write a tombstone, drop the manifest entry.

### Changed

- **`SessionWatcher`** — on a live change, call
  `SessionArchiveService.sync(live)`; if it returns an `archive_path`, index that
  path (not the live path).
- **`SessionIndexService`** — index archive paths. Chunk metadata:
  `source_path` = archive path; new `origin_path` = live `~/.claude` path (for
  provenance). Subagent path parsers updated to resolve the archive layout.
- **`config/session_config.py`** — additive `archive` block.
- **`status`** — session line reports archive counts.

## On-disk layout

All under the gitignored `.brainpalace/` (no hardcoded git exception needed).

```
.brainpalace/session_archive/
  2026-06-01/                                # dated by session started_at
    s_4f2a9c.jsonl                           # full raw transcript, verbatim
    s_4f2a9c/subagents/agent-7b1.jsonl       # subagent transcripts preserved
  manifest.json    # session_id -> {origin_path, archived_date, src_mtime,
                   #                 src_size, indexed_hash}
  tombstones.json  # session_id -> {deleted_at, origin_path}
```

- Dated folder name = `started_at` date (`YYYY-MM-DD`).
- Resume appends to the live file → re-sync **overwrites the same**
  `<session_id>.jsonl`. Never a second copy.
- Subagent sub-structure is preserved so `is_subagent_path` /
  `parent_session_id_for` resolve against the archive path.

## Data flows

### Sync (live change → archive)
1. `SessionWatcher` fires on a `~/.claude/.../*.jsonl` change.
2. Resolve `session_id` and `started_at` date from the file.
3. If `session_id` ∈ tombstones → **skip** (no resurrection).
4. If src `mtime`/`size` == manifest entry → **skip** (no-op).
5. Copy verbatim to `session_archive/<date>/<session_id>.jsonl`; sync
   `subagents/`.
6. Update manifest; pass `archive_path` to `SessionIndexService`.

### Index
- Unchanged session-aware chunker runs on the archive copy.
- Content-hash dedup re-embeds only changed windows.
- `retain_days` gates **indexing only** — archives older than `retain_days` stay
  on disk, simply unindexed (re-indexable later).

### Resume
- Live file grows → mtime change → re-sync overwrites the same archive file →
  re-chunk → dedup re-embeds only new windows.

### Delete (curation)
1. User removes an archive `<session_id>.jsonl` or dated folder (file manager).
2. `SessionArchiveWatcher` detects the deletion.
3. Purge that session's chunks from the index (by `session_id`).
4. Write a tombstone (`deleted_at`, `origin_path`); drop the manifest entry.
5. Future syncs skip the session (Sync step 3).
- Re-archiving a tombstoned session: remove its `tombstones.json` entry
  (documented; no command in v1).

### One-time backfill (on enable/upgrade)
- When the feature first becomes active, `backfill()` syncs all existing live
  transcripts into the archive, reindexes from the archive, and drops any
  legacy live-path session chunks (uniform archive-based index).
- Idempotent via the manifest (already-synced unchanged files are skipped).

### `~/.claude` invariant
- Opened for **read + stat only**. Nothing writes to or deletes from it.

## Config

Additive; defaults preserve current behavior for existing users.

```yaml
session_indexing:
  enabled: true
  archive:
    enabled: true                       # default true when session_indexing on
    dir: .brainpalace/session_archive   # overridable
  include_user_turns: false             # INDEXING filter only
  retain_days: 90                       # gates indexing; archive kept forever
```

- **The archive is ALWAYS the full raw transcript** (user + assistant + tool
  turns). `include_user_turns` filters only what is **indexed**, never what is
  archived.

## Reset / privacy semantics

- `brainpalace reset` (clear index) **never** touches `session_archive/`. The
  index is re-derived from the archive on the next run.
- A new `--include-sessions` flag on reset is the **only** way to delete
  archives; off by default (destructive path stays opt-in).
- Privacy: full raw prompts persist to disk inside the project (gitignored).
  `SESSION_INDEXING.md` must state plainly that `include_user_turns` does **not**
  filter the archive — the raw copy keeps everything.

## Error handling

- Sync copy failure (permission/space): log, leave manifest unchanged, do not
  index a partial copy; retried on next change event.
- Manifest/tombstone JSON corruption: treat as empty + rebuild from the archive
  tree (filenames are authoritative); log a warning.
- Deletion watcher racing a concurrent re-sync: tombstone wins — a tombstoned
  session is not re-synced even if a live change event arrives later.
- Backfill interrupted: idempotent; resumes from the manifest on next start.

## Status integration

`brainpalace status` session line adds:
`archived: N sessions (M MB), tombstoned: K`.

## Testing

- **`SessionArchiveService`**: sync new / unchanged (mtime no-op) / resumed
  (mtime change → overwrite) / tombstone-skip; subagent sync; manifest
  round-trip; corruption recovery.
- **`SessionArchiveWatcher`**: deletion → chunk purge + tombstone + manifest
  drop.
- **`SessionIndexService`**: `source_path` = archive, `origin_path` = live;
  backfill idempotency; `retain_days` bounds index not archive.
- **Reset**: archive survives plain reset; wiped only with `--include-sessions`.
- **E2E**: live write → archive → index → query hit; delete → query miss + no
  resurrection on the next sync.

## Affected files (anticipated)

- New: `services/session_archive_service.py`,
  `services/session_archive_watcher.py`, tests for both.
- Changed: `services/session_watcher.py`, `services/session_index_service.py`,
  `indexing/session_loader.py` (path parsers), `config/session_config.py`,
  status command/service, `reset` command (`--include-sessions`),
  `docs/SESSION_INDEXING.md`.
