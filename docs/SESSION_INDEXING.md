---
last_validated: 2026-06-02
---

# Session Indexing

Make your past AI-coding sessions searchable. BrainPalace can parse the runtime
JSONL transcripts your coding tool already writes (e.g. Claude Code under
`~/.claude/projects/<encoded-cwd>/*.jsonl`) into searchable chunks, so later you
can ask *"what did we decide about retries?"* or *"where did we touch the auth
module?"* and get hits from prior sessions through the normal `query` path.

> **Status (Phase 050 — core).** This phase indexes sessions for **keyword +
> semantic recall**. There is **no LLM extraction yet** — summaries, decisions,
> and a knowledge graph come in later phases (060/100). Re-ingest is cheap
> (content-hash dedup); nothing is summarized or sent to an LLM here.

## Two independent capabilities

Session handling splits into **two separate switches** — you can run either
without the other:

| Capability | What it does | Cost | Default |
|---|---|---|---|
| **archive** | Copies raw `.jsonl` transcripts into `.brainpalace/` as a durable backup. No embeddings. | Free (disk only) | **ON** — including existing projects |
| **index** | Embeds archived transcripts into the vector store for semantic/keyword recall. | Billable (embedding tokens) | ON for new projects; **OFF** for existing |

Archiving exists because Claude Code prunes transcripts older than ~30 days;
the archive is a durable backup that survives that. Indexing is the billable,
opt-in search layer on top.

## Privacy & defaults — read this first

The decision matrix turns on whether your project `config.yaml` has a
`session_indexing:` block:

- **No block (existing projects):** **archive ON, index OFF.** Your transcripts
  are backed up to `.brainpalace/session_archive/` but **nothing is embedded** —
  no surprise embedding cost. This is the accepted default; see the privacy note
  below since the archive contains *full raw transcripts*.
- **Block present (new `brainpalace init`):** **both ON.** `init` writes
  `session_indexing.enabled: true` and `session_indexing.archive.enabled: true`.
  Interactive runs confirm the index (default yes); non-interactive / `--json`
  runs enable both. Disable per capability: `init --no-sessions` (index off,
  archive stays on) or `init --no-archive` (archive off, index stays on).

Other guarantees:

- **Assistant-weighted indexing.** Human *user* dialogue turns are **excluded by
  default** (`include_user_turns: false`) from the *index*. This filter does
  **not** apply to the archive — see the privacy note below.
- **Index stores only derived chunks.** Per ADR 0001 the indexed store holds
  derived chunks that **reference** the `session_id` + file path; the *archive*
  is the verbatim copy.
- **Global kill-switches.** `SESSION_INDEXING_ENABLED=false` forces the index
  off; `SESSION_ARCHIVE_ENABLED=false` forces the archive off — each regardless
  of any project config.

## Enabling it

Add a `session_indexing:` block to your project `config.yaml` (the same file the
`graphrag:` block lives in — `.brainpalace/config.yaml`):

```yaml
session_indexing:
  enabled: true            # INDEX: embed transcripts (billable). init writes true; opt out: init --no-sessions
  retain_days: 0           # index age cutoff in days; <=0 = forever (no cutoff)
  include_user_turns: false # INDEX filter only — the archive is always full raw
  window: 4                 # turns per sliding window (3–5)
  stride: 2                 # window stride in turns
  watch_debounce_ms: 30000  # live-watch debounce; sessions are bursty, batch a turn
  archive:
    enabled: true          # ARCHIVE: copy raw transcripts (independent of index)
    dir: .brainpalace/session_archive  # default; override if needed
    retain_days: 0         # archive age cutoff in days; <=0 = forever (separate from index)
  # sessions_dir: /custom/path   # optional override of the auto-resolved dir
```

**`retain_days <= 0` means keep forever** (no age cutoff), for both index and
archive independently. A positive value skips files older than
`now - retain_days*86400`. ⚠️ First-run indexing with `retain_days: 0` over a
large transcript history can be a big embedding bill — set a positive cutoff if
that matters (this only applies when *index* is enabled).

**`watch_debounce_ms`** (default `30000`) batches the live session watcher. AI
transcripts are written per message in bursts (long quiet during generation, then
a burst of lines), so a short debounce fires redundant re-index passes mid-turn
on an in-progress file. 30s batches a whole turn. Freshness is low-value here —
recall targets *past* sessions, not the live one. Lower it only if you really
want near-live indexing of the current session.

By default BrainPalace resolves your session directory automatically by encoding
the project path the way Claude Code does (`/` → `-`), e.g. project
`/home/me/work/app` → `~/.claude/projects/-home-me-work-app/`.

### Embedding cost — read before enabling

Session memory embeds **every** sliding window of your transcripts, and the
default `window: 4` / `stride: 2` means **50% overlap** — each turn is embedded
in roughly two windows. On a real project this adds up fast: ~26 transcripts
produced ~1,200 session chunks (~400k OpenAI embedding tokens) in one indexing
pass. If you index sessions continuously you can burn six figures of embedding
tokens in an hour.

This is by design (overlap improves multi-turn recall), but it is the single
biggest cost driver of session memory. Two cheap levers:

- **`stride: 4` (no overlap)** ≈ halves embedding cost, at some recall loss on
  context that straddles a window boundary.
- Use a **local embedding provider** (Ollama) for sessions if cost matters more
  than retrieval quality.

The graph extraction path (summaries/decisions/triplets) does **not** embed and
costs nothing beyond your subscription — only the `session_turn` window indexing
above incurs embedding spend.

## What gets indexed

- A new chunk **source type**: `source_type="session_turn"`. Query just sessions
  with `brainpalace query "…" --source-types session_turn`.
- **Sliding windows** of conversation turns (default 4 turns, stride 2) so
  multi-turn context stays together. Fenced code blocks set `has_code_block`
  and a detected `language`.
- **Rich metadata** on every chunk: `session_id`, `started_at`, `turn_index`,
  `tools_used`, `files_touched` (from direct tool file inputs only),
  `branch`, `is_subagent`, `parent_session_id`, `source_path`.
- **Sub-agent transcripts** (`…/<parent-session-id>/subagents/agent-*.jsonl`)
  are indexed as their own sessions and **linked** to the parent via
  `parent_session_id` — rather than guessing what a sub-agent did from the
  parent's summary (which proved lossy in the 020 extraction spike).
- **Dedup.** Each chunk's id is a content hash, so re-indexing an unchanged
  session re-embeds nothing.
- **Retention.** Transcripts older than `retain_days` are skipped for indexing
  (`<= 0` = forever; a roll-up summary for old sessions arrives with the LLM
  phases). The archive has its own `archive.retain_days`.

## Archive & durability

When a live transcript changes, BrainPalace copies the raw `.jsonl` **verbatim**
into a local archive. Archiving runs **whenever the archive capability is on**,
independent of indexing — so an archive-only project (e.g. an existing project
with no `session_indexing` block) still backs up every transcript without
embedding anything. When indexing is also on, the server indexes the archive
copy, not the live file.

### Archive location

Date folders are **tool-tagged** `YYYY-MM-DD-<tool>` so same-day sessions from
different tools sort adjacently and future multi-tool support (Codex, Gemini,
OpenCode) slots in cleanly. Today the only tool is `claude-code`:

```
.brainpalace/session_archive/<YYYY-MM-DD>-<tool>/<session_id>.jsonl
# e.g. .brainpalace/session_archive/2026-06-01-claude-code/s_abc.jsonl
```

Subagent transcripts nest under their parent's tool-dated folder:

```
.brainpalace/session_archive/<YYYY-MM-DD>-<tool>/<parent_id>/subagents/<session_id>.jsonl
```

Each manifest entry stores `tool` as a **structured field** — that field, not
the folder path, is the source of truth (consumers must not parse paths). The
archive directory is gitignored (local only, never committed).

### Full raw transcripts — privacy implication

The archive always contains **the full raw transcript**, including user turns,
regardless of the `include_user_turns` setting. `include_user_turns` only
controls what gets indexed (searchable chunks); it does not filter the archive.

**Concretely:** if `include_user_turns: false` (the default), your prompts are
never indexed but they **are** present in `.brainpalace/session_archive/` on
disk. If you want a session's raw prompts removed, delete the archived `.jsonl`
file (see Curation below).

### Durability

Because the archive is a copy independent of `~/.claude`, sessions survive
Claude Code removal, transcript auto-deletion, or directory cleanup. The
archive is the stable source of truth for re-indexing.

`~/.claude` is **read-only** to BrainPalace — it only reads and copies from
that directory; it never writes to or deletes from it.

### Curation by filesystem deletion

To remove a session from the index permanently:

1. Delete the archived `.jsonl` (or an entire dated folder to remove all sessions
   from that day).
2. The archive watcher detects the deletion, writes a **tombstone** entry, and —
   *only when indexing is on* — purges that session's index chunks. With index
   off there are no chunks, so it just tombstones and drops the manifest entry.
3. The tombstone prevents resurrection: if the same session later appears as a
   live transcript change, the server skips it rather than re-syncing.

There is no separate curation command — the filesystem is the interface.

### `retain_days` and `brainpalace reset`

- **`retain_days`** (top-level) gates **indexing**: transcripts older than the
  cutoff are not indexed. `<= 0` means forever (no cutoff).
- **`archive.retain_days`** gates the **archive** independently (also `<= 0` =
  forever). Disk growth with a forever archive is accepted by design.
- Disable a capability by **removing/disabling its block or flag**, not via
  retention. `retain_days: 0` keeps everything; it does not disable anything.
- **`brainpalace reset`** clears the vector/BM25 index but **preserves** the
  archive by default. Pass `--include-sessions` to also delete
  `.brainpalace/session_archive`:

  ```bash
  brainpalace reset                    # index cleared; archive kept
  brainpalace reset --include-sessions # index + archive both deleted
  ```

### Status reporting

`brainpalace status` shows the two capabilities on **separate rows** so all four
states (archive on/off × index on/off) are legible:

```
Session Archive: on — 463 files, 12.3 MB (forever)
Session Memory:  off (enable: brainpalace init --sessions)
```

Archive metrics:

| Field | Meaning |
|---|---|
| `archived_files` | number of `.jsonl` files in the archive |
| `archived_sessions` | distinct sessions (parent + subagents count as one) |
| `archived_bytes` | total size of the archive on disk |
| `tombstoned` | sessions deleted from the archive and blocked from re-sync |

## Recall tiers

Session recall follows the tiered ladder (see [SESSION_CONTEXT.md](SESSION_CONTEXT.md)):

1. **Indexed `session_turn` chunks** — vector + BM25 over the windows above
   (this phase).
2. **Summaries / decisions / graph** — added in 060/100.
3. **Raw JSONL on disk** — the verbatim L3 tier; always the ground truth, never
   copied into the store.

## Submitting an extraction (summaries, decisions, triplets)

Indexed turns give you raw recall. To store a *distilled* view of a session —
a summary, the decisions made, and relationship triplets — submit an
**extraction payload**. The LLM that produces it runs inside your AI coding
tool (the manual command in 070, the SessionEnd subagent in 080); the server
never calls an LLM, so this costs nothing beyond your existing subscription.

```bash
# payload.json matches the extraction schema (see below)
brainpalace submit-session <session_id> --json payload.json
# or pipe it:
some-extractor | brainpalace submit-session <session_id> --json -
```

This persists, idempotently on `session_id`:

- a `session_summary` chunk + one `session_decision` chunk per decision
  (queryable: `brainpalace query "…" --source-types session_summary,session_decision`),
- relationship **triplets** into the knowledge graph (best-effort — a no-op when
  graph indexing is disabled, which is the default),
- an entry in a **git-tracked decisions digest** (`BRAINPALACE_DECISIONS.md`) —
  decisions only, never raw dialogue (ADR 0001). The human-reviewable, diffable
  record of what was decided.

Re-submitting the same `session_id` overwrites its chunks and digest block (no
duplicates), so a SessionEnd hook can submit freely.

### Extraction schema (summary)

One JSON object per session: `session_id`, `summary`, `open_threads[]`,
`decisions[{text, rationale, files[], supersedes}]`,
`files_touched[{path, action: edit|create|read}]`, `tools_used[]`,
`triplets[{subject, relation, object, evidence_turn}]`. `relation` is a closed
vocabulary: `touches`, `fixed-by`, `superseded-by`, `ran-in`, `depends-on`,
`decided`. The server validates strictly (unknown keys / relations rejected).

### Producing the payload

You don't have to hand-write the extraction JSON. Two paths, same contract:

- **Manual (any runtime):** `/brainpalace:brainpalace-extract-session` has your
  AI read the current transcript, distil it, and pipe it into
  `brainpalace submit-session`.
- **Automatic (Claude Code):** the **queue-and-drain** hooks below extract
  finished sessions on their own — for free, on your subscription model.

### Automatic extraction (Claude Code) — queue-and-drain

Claude Code `SessionEnd` hooks are shell-only and can't run an LLM for free at
end-of-session. So extraction is split:

1. **`templates/sessionend-hook.sh`** appends the just-ended `session_id` to a
   per-project queue (`.brainpalace/extract-queue.txt`). Instant, no LLM, only
   for indexed projects.
2. The **SessionStart hook** drains that queue at the *next* session start: it
   asks the in-session model to run the **`chat-session-extractor`** subagent on
   each queued session, which extracts + submits. Free (subscription model);
   no `claude -p` headless spend, no paid cron.

Install the SessionEnd hook alongside the SessionStart hook (see each
template's header). Extraction is **best-effort** — if the model doesn't drain a
queued session, the manual command is always available.

### Periodic curation (opt-in)

Two more opt-in SessionStart hooks keep curated memory (the
[memory namespace](MEMORY.md)) fresh via the `memory-curator` subagent, again on
the subscription model:

- **`templates/daily-distill-hook.sh`** — once/day, pull durable facts from
  recent sessions into curated memory (`brainpalace remember`).
- **`templates/weekly-curate-hook.sh`** — once/week, obsolete superseded
  memories, delete duplicates, enforce caps.

## Querying the session graph

Extracted triplets land in the knowledge graph as **typed** nodes (Phase 100 —
see [GRAPH_TAXONOMY](GRAPH_TAXONOMY.md)). Query them with GRAPH mode (requires
`ENABLE_GRAPH_INDEX=true`; the `sqlite` backend is recommended once the graph
grows — see [GRAPHRAG_GUIDE](GRAPHRAG_GUIDE.md#storage-backends)).

**1. What fixed an error (failed approaches → resolution).** `fixed-by` edges
link an `Error` to the `Decision` that resolved it:

```bash
brainpalace query -m graph "login 500 timeout"
# → Error 'login 500' --fixed-by--> Decision 'raise token-expiry to 24h'
```

**2. Decisions touching a file.** `touches` edges originate at a `File`;
`decided`/`fixed-by` edges point at `Decision`s. Query the file to surface the
decisions and edits around it:

```bash
brainpalace query -m graph "auth.py"
# → File 'auth.py' --touches--> 'JWT refresh flow'
#   Session 's_4f2' --decided--> Decision 'store refresh token server-side'
```

**3. Supersedes chains (decision history).** `superseded-by` edges chain older
decisions to newer ones (`A superseded-by B` means **B replaces A**):

```bash
brainpalace query -m graph "cache backend decision"
# → Decision 'in-memory dict cache' --superseded-by--> Decision 'Redis cache'
```

On the `sqlite` backend each edge also carries a validity window, so a consumer
can `invalidate()` the superseded decision (dropping it from default results)
while `timeline()` still reconstructs the full chain. See
[GRAPH_TAXONOMY](GRAPH_TAXONOMY.md#composing-with-temporal-validity-phase-090).

## Related

- **Time-decay ranking** (newer sessions/commits rank higher) — see
  [CONFIGURATION](CONFIGURATION.md#time-decay-ranking).
- **Cross-session linking** (entity canonicalisation, decision supersession,
  promotion to curated memory, stale-decision penalty) — see
  [GRAPH_TAXONOMY](GRAPH_TAXONOMY.md#cross-session-linking-phase-140).

## Not yet (later phases)

- Typed LSP cross-reference graph — **150** (→ v11).
