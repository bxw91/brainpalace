---
last_validated: 2026-07-10
---

# Curated Memory

A small, high-signal store of **durable facts** about your project — separate
from the auto-indexed code/docs. You write them with `remember`; they surface at
the top of normal `query` results and can be retrieved directly with `recall`.

> **Source of truth is git-tracked markdown.** Memories live in
> `BRAINPALACE_MEMORY.md` at your repo root (commit it). The vector index is a
> rebuildable shadow — deleting `.brainpalace/` and re-indexing loses no
> memories. (ADR 0001.)

## Why a separate namespace

Auto-indexed chunks are high-volume, low-signal-each. Curated memory is the
opposite: a handful of facts you (or, later, the AI) deliberately keep — "staging
URL is X", "this project's Supabase tables use prefix Y", "we chose Z because W".
They're boosted above generic chunks and survive a database wipe.

## CLI

```bash
brainpalace remember "staging url is staging.example.com" --tags infra --section Environment
brainpalace recall "staging url"          # memory namespace only
brainpalace memories list                 # table of all memories
brainpalace memories list --tag infra     # filter
brainpalace memories show mem_1a2b3c4d
brainpalace memories obsolete mem_1a2b3c4d --superseded-by mem_9f8e7d6c
brainpalace memories delete mem_1a2b3c4d
```

A normal query automatically boosts relevant memories:

```bash
brainpalace query "where do we deploy staging"   # a matching memory ranks first
brainpalace query "..." --no-memory               # disable the boost for this query
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/memories/` | create a memory |
| `GET` | `/memories/` | list (filters: `tag`, `section`, `include_obsolete`) |
| `POST` | `/memories/recall` | recall, memory namespace only |
| `DELETE` | `/memories/{id}` | delete |
| `POST` | `/memories/{id}/obsolete` | mark obsolete (kept in file, dropped from index) |
| `POST` | `/memories/rebuild` | rebuild the shadow index from the markdown |

## MCP tools

`memorize(text, section?, tags?)` and `recall(query, k?)` — same surface, for
agents driving BrainPalace over MCP.

## Markdown format

```markdown
# BrainPalace Memory

## Environment
- staging url is staging.example.com <!-- ab:id=mem_1a2b3c4d tags=infra origin=user conf=1.0 created=2026-05-29T... last_ref= obsoleted= superseded_by= -->
```

Entries are `- <text> <!-- ab:... -->` list items under `## <section>` headers.
You can hand-edit the file; untagged lines are preserved. After a hand edit run
`brainpalace memories list` (or restart the server) — the index self-heals from
the markdown on boot when it's empty.

## How the boost works

A query runs an extra small vector pass over the memory namespace, multiplies
each hit's score by `MEMORY_BOOST` (default 1.5), drops anything below
`MEMORY_MIN_SCORE` (default 0.35), and merges the survivors into the results.
Pure `bm25` mode is unaffected; `--no-memory` / `use_memory=false` disables it.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `MEMORY_ENABLED` | `true` | master switch |
| `MEMORY_PATH` | (repo root `BRAINPALACE_MEMORY.md`) | markdown source-of-truth path |
| `MEMORY_CHAR_CAP` | `8000` | hard cap on the markdown file (forces curation) |
| `MEMORY_BOOST` | `1.5` | score multiplier for memory hits in `query` |
| `MEMORY_RECALL_K` | `3` | memory hits considered in the boost pass |
| `MEMORY_MIN_SCORE` | `0.35` | relevance floor before a memory can boost in |
| `MEMORY_COLLECTION` | `brainpalace_memories` | Chroma shadow-index name |
| `MEMORY_CURATE_INTERVAL_DAYS` | `7` | minimum days between curation runs (cadence for BOTH the in-session nudge and the server-side curator) |
| `MEMORY_DEDUPE_THRESHOLD` | `0.92` | write-time supersede floor: a new `remember` fact whose top embedding match to an active memory scores ≥ this supersedes it (newest wins) |

When the file hits the cap, manual `remember` refuses — obsolete or consolidate
entries first. The cap keeps memory curated and small (high signal).

## Eviction & cap reclaim

Auto-promoted decisions (`origin=session:*`, written by server-side
`promote_decisions`) go through a **reclaim-aware** write path so a full memory
file never silently goes read-only:

- **Eviction.** When admitting a new auto-promoted fact would exceed the cap,
  the worst evictable entries are physically deleted first — worst-first by
  oldest reference (falling back to creation time), then lowest confidence —
  until the new fact fits.
- **Manual facts are sacred.** Only `origin=session:*` entries are evictable;
  `origin=user` facts (from `remember`) are **never** auto-evicted.
- **Cross-session supersession.** A promoted decision carrying `supersedes`
  deletes the prior matching session-decision entry (exact decision-text match),
  so the superseding fact replaces it instead of piling up.
- **Write-time dedupe.** When embeddings + shadow index are available, a manual
  `remember` whose top embedding match to an active memory scores ≥
  `MEMORY_DEDUPE_THRESHOLD` (default `0.92`) supersedes that entry — re-asserting
  a fact replaces its near-duplicate (newest wins) instead of adding a second
  copy. Embeddings-only (no LLM); a no-op when the shadow index is absent.
- **Loud fallback.** If only protected manual facts remain and the cap is still
  hit, the promotion is skipped and a cap-pressure marker
  (`memory_cap_pressure.json`) is written beside the memory file. `brainpalace
  status` surfaces it as a `⚠ cap pressure — N promotions skipped` warning
  instead of dropping decisions silently; a later successful promotion clears it.

## Auto-curation (gated by `extraction.mode`)

Curation rides the single `extraction.mode` (session) switch — there is no
separate enable toggle. The mode selects which path runs, at most once per
`MEMORY_CURATE_INTERVAL_DAYS` (the shared cadence for both):

- **`subagent` / `auto` → in-session nudge.** The auto-wired `brainpalace hook
  sessionstart` appends a best-effort directive nudging the model to run the
  `memory-curator` subagent (obsolete superseded entries, delete duplicates,
  consolidate verbose ones, keep under the cap). The server computes the
  `curate_due` gate as a pure predicate (reads the weekly stamp, never writes
  it); the CLI stamps `.brainpalace/last-curate` only when it actually emits the
  nudge, so a non-emitting context fetch never consumes the due state.
- **`provider` / `auto` → server-side curator.** A `MemoryCurator` shares the
  configured summarization provider (like `SessionDistiller`) and runs on the
  periodic reconcile sweep. It carries the second cost-lock
  `EXTRACTION_PROVIDER_ENABLED` (and the distiller gate `SESSION_DISTILL_ENABLED`)
  — no paid tokens without it. It stamps `.brainpalace/last-curate` server-side
  after a completed run (even at 0 changes); a provider/parse failure leaves the
  stamp untouched so the run retries next sweep. All mutations go through
  `MemoryService` (cap + lock honored).
- **`off` → no curation** on either path.

## Session-start injection

Beyond the query boost, curated memory is also pushed into the AI's context at
**session start** via `brainpalace context` (Phase 035) — so it begins each
session already knowing your durable facts. See
[SESSION_CONTEXT.md](SESSION_CONTEXT.md).

## Security

Memory is **user-curated**, not auto-captured. Keep secrets out of it — record
credential *names*, never values. The file is meant to be committed to git.
