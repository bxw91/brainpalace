---
last_validated: 2026-06-18
---

# Git History Indexing

Make your repo's **git history** searchable. BrainPalace can walk `git log` and
index each commit — its message plus a truncated diff stat — as a new chunk
type, bridging *why* (sessions, decisions) ↔ *what* (code). Ask
*"why did we switch the cache backend?"* and the commit that did it surfaces
through the normal `query` path, with full commit metadata.

> **Status (Phase 130 — core).** This indexes commits for **keyword + semantic
> recall**. There is **no LLM extraction** — the commit message and a diff-stat
> summary are embedded as-is. Re-index is cheap (sha-addressed dedup +
> incremental `since-sha`); nothing is summarized or sent to an LLM here.

## Privacy model — read this first

Git-history indexing is **OFF by default** and strictly opt-in per project.

- **Disabled unless you opt in.** With no `git_indexing:` block, no history is
  read or indexed.
- **Diffs can contain secrets.** Indexing commit content can ingest anything
  that was ever committed — including secrets in old diffs. This is exactly why
  the feature is opt-in. By default only the **changed file paths and line
  counts** are rendered into the chunk (a diff *stat*), **not patch bodies**, so
  the indexed text is the commit message + a file list. Review your history
  before enabling on a repo with a leaky past.
- **History is never copied.** The repo on disk *is* the source-of-truth. BrainPalace stores only derived commit chunks (gitignored, rebuildable) that
  **reference** the commit `sha`; it never duplicates the repo into its store.
- **Global kill-switch.** `GIT_INDEXING_ENABLED=false` in the server environment
  forces git indexing off regardless of any project config.

## Enabling it

Add a `git_indexing:` block to your project `config.yaml`
(`.brainpalace/config.yaml`):

```yaml
git_indexing:
  enabled: true        # default: false (opt-in)
  depth: 0             # max commits on the first (full) pass; default 0 = no cap
  max_files: 50        # max changed file paths rendered into a commit chunk
  # repo_path: /custom/path   # optional; defaults to the project root
```

### Mono-repo: limiting which commits are indexed

When one `.git/` at the workspace root serves several projects (each with its
own `.brainpalace/` subfolder), git indexing walks the **whole** repo's history
by default — not just the subfolder's commits. To restrict it, set
`git_indexing.path_filter` to the subfolder path(s):

```yaml
git_indexing:
  enabled: true
  path_filter:
    - services/api
```

This runs `git log -- services/api`, so only commits that touched those paths
are indexed.

## What gets indexed

- A new chunk **source type**: `source_type="git_commit"`. Query just commits
  with `brainpalace query "…" --source-types git_commit`.
- **One chunk per commit**: subject + body + a truncated diff stat (changed
  files, `+added/-deleted` line totals, bounded by `max_files`).
- **Rich metadata** on every chunk (in `extra`): `commit_sha`, `author`,
  `author_email`, `committed_at`, `files_changed`, `lines_added`,
  `lines_deleted`, `branch_seen_on`.
- **Time decay for free.** The chunk's `created_at` is set to the commit's
  `committed_at`, so the 110 time-decay ranking treats old commits as older
  evidence automatically.

## Incremental re-index

The last-indexed commit sha is persisted under the server state dir. On
re-index, only `git log <last>..HEAD` is walked, so new commits are picked up
without re-reading the whole history. A full pass is bounded by `depth`.

- **On boot** — if enabled, the server kicks off a fail-soft boot index.
- **On demand** — `POST /git/reindex` re-runs the incremental pass. Returns
  `503` unless git indexing is enabled.

```bash
curl -X POST localhost:<port>/git/reindex
```

## Query examples

```bash
# Why did something change — surfaces the commit that did it.
brainpalace query "switch cache backend" --source-types git_commit

# Commits that touched a subsystem (matches files in the diff stat).
brainpalace query "auth middleware" --source-types git_commit
```

## Health

`GET /health/status` reports a `git_commits` count in its collection sizes
(alongside `session_chunks`) so `doctor` can confirm history is indexed.

## Limits

- **Bounded depth + truncated diffs.** Large repos are kept tractable by
  `depth` (full pass) + incremental `since-sha` + `max_files` per chunk.
- **No-git dirs.** A non-repo path indexes nothing (the service no-ops).
- **Merge commits** are walked like any other commit; their numstat reflects
  git's default diff against the first parent.
