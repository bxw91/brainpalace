---
last_validated: 2026-06-18
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

When the file hits the cap, `remember` refuses — obsolete or consolidate entries
first. The cap keeps memory curated and small (high signal).

## Session-start injection

Beyond the query boost, curated memory is also pushed into the AI's context at
**session start** via `brainpalace context` (Phase 035) — so it begins each
session already knowing your durable facts. See
[SESSION_CONTEXT.md](SESSION_CONTEXT.md).

## Security

Memory is **user-curated**, not auto-captured. Keep secrets out of it — record
credential *names*, never values. The file is meant to be committed to git.
