---
last_validated: 2026-07-04
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
| **index** | Embeds archived transcripts into the vector store for semantic/keyword recall. | Billable (embedding tokens) | **OFF** by default — opt-in at `init` (or `--sessions`) |

Archiving exists because Claude Code prunes transcripts older than ~30 days;
the archive is a durable backup that survives that. Indexing is the billable,
opt-in search layer on top. An interactive `brainpalace init` **asks** before
enabling each session feature — *Summarize?* `[Y/n]` (free, Haiku subagent) then
*Embed?* `[y/N]` (billable). Embedding is opt-in: a bare `init` (and `--yes`) keeps
it **off**; pass `--sessions` to enable it non-interactively, `--no-extract` to skip
summarization.

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
  enabled: true            # INDEX: embed chat sessions via the embedding provider. init writes true; opt out: init --no-sessions
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

**`session_archive.reconcile_seconds`** (default `600`, env
`SESSION_ARCHIVE_RECONCILE_SECONDS`) sets the **copy/index sweep interval**. The
server no longer copies on every transcript change; a periodic reconciler copies
each session into the archive at most once per interval (and indexes it when index
is on). A growing session is therefore re-copied at most once per interval, and its
**final tail is always captured** on the first sweep after it goes quiet
(`sync` dedups unchanged files — no re-copy, no re-summary). Freshness is low-value
here — recall targets *past* sessions, not the live one. Lower it only if you want
near-live archiving/indexing of the current session.

**`session_extraction.quiescence_seconds`** (default `1800` = 30 min, env
`SESSION_QUIESCENCE_SECONDS`) sets how long a session must be **idle** before it is
summarizable, so a session you merely paused is never summarized mid-work. Honored
by both the subagent drain and the provider distiller.

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
Session Archive:       on — 463 files, 12.3 MB (forever)
Session Memory:        off (enable: brainpalace init --sessions)
Session Summarization: 78% summarized (361/463 sessions, mode: subagent)
```

The **Session Summarization** row reports coverage: the percent of archived
sessions that carry a durable extraction (`.done`) marker, engine-agnostic (both
the plugin subagent and the provider distiller write the unified marker). A
backlog draining via the throttle shows this climb over time.

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

### Recall is gated on the live feature flags (hard off)

Session-derived data is only reachable via search **while its producing feature
is on**. The gate is per-feature and HARD — there is no per-query override, so an
explicit `--source-types session_turn` simply returns nothing when the feature is
off:

| Feature OFF | Hidden from every query/search |
|-------------|--------------------------------|
| Vector indexing (`session_indexing.enabled: false`) | `session_turn` chunks |
| Summarization (`extraction.mode: off`) | `session_summary` + `session_decision` chunks, and auto-promoted (`origin != user`) curated memory |

Rationale: a disabled feature's data can be **stale**, so it must not leak into
results or the SessionStart context block. Manually-saved facts
(`brainpalace remember`, `origin: user`) are unaffected — always recallable via
`brainpalace recall`. The SessionStart context block also makes its **session-recall
instruction conditional**: the agent is told prior sessions/decisions are
searchable only when the matching feature is live; with both off, no such line
appears. `brainpalace status` shows the live state on the **Session Recall** row.
Re-enabling a feature restores its recall immediately (no re-index needed for data
already in the store).

## Submitting an extraction (summaries, decisions, triplets)

Indexed turns give you raw recall. To store a *distilled* view of a session —
a summary, the decisions made, and relationship triplets — submit an
**extraction payload**. There are **two engines** that can produce it (see
[Session summarization — `subagent` default](#session-summarization--subagent-default-claude-code-only)):
the Claude Code **plugin subagent** (free on your subscription; the server never
calls an LLM — **the default**), or the opt-in **server provider engine** (the
server summarizes with your configured AI). Either way the same payload is
stored. You can also submit one by hand:

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
duplicates), so a resumed-and-grown session can be re-summarized in full and
cleanly supersede its previous summary.

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
- **Automatic (Claude Code):** the **archive-driven drain** below extracts
  finished sessions on their own — for free, on your subscription model.

### Automatic extraction (Claude Code) — archive-driven

Summarization is **archive-driven**: BrainPalace copies every Claude Code session
into `.brainpalace/session_archive/` on a periodic sweep
(`session_archive.reconcile_seconds`, default 600 s; default on). Each drain cycle
summarizes the archived sessions that still need it — **new**,
**resumed-and-grown** (the archived file is newer than its `.done` marker), or
**late-copied** — once the session is **quiescent**
(`session_extraction.quiescence_seconds`, idle ≥ 30 min by default, so it never
summarizes a session you're still typing in). The free Haiku
`chat-session-extractor` subagent reads the **archived** file (resolved by
`brainpalace session-path`), distils it, and `submit-session` writes the `.done`
marker; `SessionExtractService.store` is idempotent per session, so a resume
produces a **full re-summary that supersedes** the previous one. There is no
SessionEnd queue.

The drain runs **after the first user turn** of a session (NOT at startup): the
**UserPromptSubmit hook** (`userpromptsubmit-drain-hook.sh`) asks the in-session
model to run the **`chat-session-extractor`** subagent (pinned to **Haiku**) on
each pending session. Free (subscription model); no `claude -p` headless spend, no
paid cron. The gap is recomputed from the durable archive every run, so a pending
session is summarized at the next Claude Code session, however much later. The
legacy `sessionend-hook.sh` queue is retired and the hook has been removed.

This **extraction hook now ships with the Claude Code plugin**
(`plugin.json` `hooks`, under `${CLAUDE_PLUGIN_ROOT}/hooks/`), alongside the
plugin's **SessionStart reminder**. Installing the plugin gives you the complete
hook set — nothing else to wire. **`brainpalace install-session-hooks`** now
installs **only the SessionStart reminder** (for CLI/MCP-only users without the
plugin) and **prunes** any old extraction hooks a prior version wrote, so the
plugin and CLI never double-run. `brainpalace init` does the same automatically:
plugin present ⇒ prune only (the plugin owns everything); plugin absent ⇒ install
the reminder.

#### Drain throttling — a big backlog never clogs one turn

The drain hook doesn't dump the whole gap into one prompt. It calls
**`brainpalace drain-queue`**, which releases a **bounded batch** per turn; the
rest stay pending and surface on a later turn:

- **byte budget** (`drain_budget_bytes`, default **1 MB**): take pending sessions
  FIFO, summing each archived transcript's raw `.jsonl` size, until the next would
  exceed the budget.
- **count cap** (`drain_max_count`, default **8**): secondary guard so many tiny
  sessions can't slip under the byte budget en masse.
- **first-pick-always (no starvation):** the first pending session is taken
  *before* the budget check, so a single oversized session drains **alone** rather
  than stalling the rest. No upper "too big, skip" ceiling — the extractor chunks
  oversized transcripts safely, so nothing is dropped.
- **cooldown** (`drain_cooldown_seconds`, default **300** = 5 min): at most one
  batch per window (tracked in `.brainpalace/last-drain`), so rapid-fire prompts
  don't re-drain. A large historical backfill trickles out over your active
  working time + across sessions; a freshly-ended session still surfaces on your
  next turn (the cooldown has usually elapsed). Set `0` to drain every prompt.

Knob precedence: env var → project `session_extraction:` config → default.

```yaml
# .brainpalace/config.yaml
session_extraction:
  mode: subagent
  drain_budget_bytes: 1048576   # 1 MB per turn
  drain_max_count: 8
  drain_cooldown_seconds: 300   # 5 min
```
Env overrides: `SESSION_DRAIN_BUDGET_BYTES`, `SESSION_DRAIN_MAX_COUNT`,
`SESSION_DRAIN_COOLDOWN_SECONDS`.

Run it by hand anytime: `brainpalace drain-queue --json`.

### Opt-in time-driven drain (babysitter)

Chat-session summarization runs on the free Claude Code Haiku subagent, **after your
first prompt** — in batches of up to **8 sessions** (≤1 MB) with a **5-minute (300 s)
cool-down** between batches. That turn-driven `UserPromptSubmit` path only fires on a
real prompt — deliberately, so opening Claude Code never starts your subscription
5-hour usage window. Two coverage gaps are accepted by design: a just-ended session
waits for your next first prompt (gap A), and a session left open but idle never drains
(gap B). Filling either automatically would start the 5h window against your wishes.

If you *want* idle-time coverage, opt in with a dedicated, low-cost babysitter:

```bash
claude --model haiku        # orchestrator runs on free Haiku too
> /loop 5m /brainpalace-drain
```

Each tick runs `brainpalace drain-tick`, which is:

- **mode-gated** to the free `subagent` engine;
- **single-drainer locked** (`<project>/.brainpalace/drain-loop.lock`) so parallel
  worktrees / multiple babysitters dedup to one live drainer; a stale lock (dead pid or
  older than 15 min) is reclaimed;
- **self-terminating** after N consecutive empty drains
  (`drain_loop_empty_stop`, env `SESSION_DRAIN_EMPTY_STOP`, default 3) so the loop can
  never silently keep the 5h window open. It writes
  `<project>/.brainpalace/drain-loop.heartbeat` each tick so a future session can detect
  a dead loop.

**Honest limits:** while the loop runs it keeps the 5h window open (each tick is a model
turn); it self-terminates once the gap stays empty; and it dies on crash/close —
losing **zero** data (the gap is recomputed from the durable archive each run; backlog
drains on your next real work turn). Summarizing while Claude Code is fully closed is
impossible on the free path by design — only the billable provider engine can do that,
and it is disabled by default.

`drain-tick` summarizes **archived** sessions that still need it, so OLD chats are picked
up automatically (as long as they were archived) — no enqueue step. `brainpalace
backfill-sessions` just confirms archiving is on.

## Session summarization — `subagent` default (Claude-Code-only)

`brainpalace init` enables session summarization by default and writes
`extraction.mode: subagent` to `.brainpalace/config.yaml`. In `subagent`
mode summaries are produced **only inside Claude Code** (the plugin, free on your
subscription). **The server never summarizes on its own and never calls a paid
provider.** If Claude Code did not summarize a session, it simply stays
un-summarized — no surprise API bill.

| Mode | Behaviour | Who summarizes | Cost |
|------|-----------|----------------|------|
| `subagent` *(default)* | plugin path only; server never distils | the plugin's `chat-session-extractor` subagent (Haiku), drained after your first turn | free† |
| `provider` *(opt-in‡)* | force the server path | the **server**, with your configured summarization AI | Ollama = free; cloud = **metered** |
| `auto` *(opt-in‡)* | plugin present ⇒ defer to subagent; plugin absent (or un-marked > 24h) ⇒ the server distils via provider | runtime-decided (subagent or provider) | free† with plugin; else Ollama free / **cloud metered** |
| `off` | `brainpalace init --no-extract` | nobody | — |

> **† "free" = no separate API bill.** The plugin's subagent runs on **your
> Claude Code subscription** (Haiku), so it draws on your subscription's usage
> limits rather than a metered API key. Ollama (`provider`/`auto`) is the only
> truly-$0 server-side option (fully local).

> **Why `subagent` is the default.** `provider` and `auto` can summarize via a
> **paid** cloud AI (the `init` default summarization provider is metered), and
> `auto`'s 24h safety net would fire that paid path automatically even with the
> plugin installed. To keep summarization cost **opt-in, never surprising**, the
> default keeps it inside Claude Code only.

> **‡ Server-side summarization needs TWO locks lifted.** The provider distiller
> is **disabled by default** (`SESSION_DISTILL_ENABLED` absent ⇒ off), *independently*
> of `mode`. So `provider`/`auto` only ever bill when **both** hold:
> `extraction.mode: provider` (or `auto`) **and** `SESSION_DISTILL_ENABLED=true`
> (`1`/`true`/`yes`/`on`). This second lock is mode-independent, so it also keeps
> any pre-existing `mode: auto` config from billing until you deliberately enable
> it. To turn on server-side summarization:
>
> ```bash
> # 1. choose the engine
> #    .brainpalace/config.yaml → extraction.mode: provider
> # 2. lift the global lock for the server process
> export SESSION_DISTILL_ENABLED=true
> ```

**Opt-in: `auto` reconciliation.** When you set `mode: auto`, the server's
distiller checks plugin presence **per session**. When the plugin is present it
**defers** (the plugin's subagent owns extraction) — **unless** the session is
un-marked AND older than a **24h grace window** (`SESSION_DISTILL_GRACE_HOURS`,
default 24), the safety net for a disabled or never-reopened plugin. A **unified
`.done` marker** (written by both the subagent submit and the provider distil)
means a live engine flip never re-summarizes an already-extracted session.

Plugin presence is detected via a **registry-first contract** (mirrored in server
+ CLI): parse `~/.claude/plugins/installed_plugins.json` for a `brainpalace@…`
key, with a directory-glob fallback.

Force a specific engine by setting `mode` by hand (`subagent`/`provider`/`auto`).
Precedence: the project `.brainpalace/config.yaml` wins over the global XDG
config; absent in both ⇒ default `subagent`.

### Coverage guarantee — opt-in (`provider`/`auto` **and** `SESSION_DISTILL_ENABLED=true`)

In the default `subagent` mode the server makes **no** summarization guarantee:
if Claude Code doesn't run (plugin absent/disabled), sessions stay un-summarized
by design. The "every session gets summarized" guarantee below applies **only
when you opt into `provider` or `auto` AND set `SESSION_DISTILL_ENABLED=true`.**

With both locks lifted there is **no code path that silently skips a session.**
The *only* ways summarization does not happen are:

1. `extraction.mode: off` (`brainpalace init --no-extract`),
2. `extraction.mode: subagent` *(the default — plugin-only, no server fallback)*, or
3. `SESSION_DISTILL_ENABLED` unset/false *(the default — provider distiller disabled)*.

Otherwise (under `provider`/`auto` with the switch on) everything is **retried until it succeeds** —
large transcripts (chunked + hierarchically merged, never skipped), malformed LLM
output (retried, then left un-marked), provider outages, server restarts, missed
real-time events, and old/pre-existing transcripts. The safety nets:

- **provider mode (and `auto` without the plugin):** a per-session
  `.brainpalace/extracted/<id>.done` marker is written **only on full success**;
  the server's **catch-up sweep** (on startup and after each archive) re-distils
  any quiescent, un-marked transcript. The live (still-growing) session is never
  distilled — only after it is idle ≥ 5 min or a newer session exists.
- **subagent mode (and `auto` with the plugin):** the **durable**
  `extract-queue.txt` holds pending ids until drained. In `auto` only, the
  server's 24h safety net still distils any session the plugin left un-marked
  past the grace window — so coverage holds even if the plugin is later disabled.
  In the default `subagent` mode there is no such fallback.

### Session filter contract (shared)

Both engines feed the LLM the **same moderate-filtered** view of a transcript, so
the provider engine and the plugin agent can't drift. The contract (enforced by
`tests/test_session_filter_contract.py` against `filter_transcript()`):

- **Kept:** user/assistant **text**, condensed **thinking**, **tool_use** (tool
  name + key inputs only — `file_path`, `command`, `path`, `pattern`, `query`,
  `description`, `old_string`, `url`, `prompt`, `content`), and **truncated
  tool_result**.
- **Dropped:** `attachment`, `file-history-snapshot`, `queue-operation`, and any
  non-conversational record type; arbitrary tool inputs outside the key set.

### Backfilling old sessions

`brainpalace backfill-sessions` summarizes a project's **pre-existing** chats in
whichever engine is configured:

```bash
brainpalace backfill-sessions                 # this project, configured engine
brainpalace backfill-sessions --limit 20      # cap how many transcripts
brainpalace backfill-sessions --force         # provider: re-distil even marked ones
```

- **subagent mode:** appends old session ids to `extract-queue.txt` (deduped) —
  drained at the next Claude Code first turn.
- **provider mode:** calls `POST /sessions/distill` so the server distils them.
  Largely redundant with the catch-up sweep; use it for on-demand / `--force`.

### Cost & privacy (provider mode)

Provider mode uses **whatever AI you configured** — there is no cost/privacy
block in code. Transcripts can contain secrets, so for the provider engine prefer
a **local Ollama** summarizer (free + private). CLI-only users are *informed*
that installing the plugin is cheaper (subscription model); it is informational
only, never enforced.

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
  File-like mentions that name an indexed code file or symbol additionally
  resolve onto the canonical code graph node (deterministic, never-guess;
  unresolved mentions stay session-domain string nodes). Effectively
  SQLite-only — the `simple` graph backend lacks the exact-lookup methods
  resolution needs, so it degrades to "no link" there.

## Not yet (later phases)

- Typed LSP cross-reference graph — **150** (→ v11).
