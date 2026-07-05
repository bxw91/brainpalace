---
last_validated: 2026-07-05
---

# Compute Query Mode & Records Subsystem

Answer set-level questions — totals, averages, superlatives — over typed numeric
measurements that BrainPalace accumulates from your AI-coding sessions. Unlike
document retrieval, compute returns aggregated rows, not text chunks.

> **Status — Phase 0–1.** The records store and the `compute` query mode are
> live. Records are populated from session extraction. **This repo has
> `extraction.mode: off`**, so compute returns empty here until that is
> changed — that is expected, not a defect.

## What it is and when to use it

Document retrieval answers *"show me context about X"*. Compute answers *"how
much X happened over time"*: "how many files did I touch last week?", "which week
had the most tool calls?", "what is the total decision count this month?".

Compute is the right mode when your question has a numeric answer from accumulated
data, not prose context. For everything else — code understanding, architecture
questions, finding decisions — use `hybrid`, `vector`, `bm25`, or `graph`.

## Records subsystem

### What a Record is

A `Record` is an immutable, typed numeric measurement:

| Field | Type | Notes |
|-------|------|-------|
| `id` | str | content hash — re-ingesting the same data never duplicates |
| `subject` | str | what was measured (e.g. `"session"`) |
| `metric` | str | name of the measurement (e.g. `"files_touched"`) |
| `value` | float | the measured quantity |
| `unit` | str or null | e.g. `"count"` |
| `ts` | str or null | ISO-8601 timestamp of the measured event |
| `domain` | str | open registry; ships `code` (default) and `chat-life`; never a closed enum |
| `source` | str or null | where the record came from (e.g. `"session"`) |
| `source_id` | str or null | id of the originating artifact (e.g. session id) |
| `ingested_at` | str or null | when the server persisted it |
| `confidence` | float 0..1 | see Confidence tiers below |
| `properties` | dict | open extension bag |

Records are frozen (immutable once created). The `domain` field is an open
registry — `code` and `chat-life` ship by default, and downstream products can
register additional domains at runtime.

### Store

Records live in a dedicated **SQLite** database (`records.db` in the project
state directory), entirely separate from the graph store and the ChromaDB/Postgres
vector store. SQLite was chosen because aggregation — the only read path — is
fast indexed column scans; there is no Postgres Records store.

**ISO-week and month bucket columns** (`iso_week` = `YYYY-Www`,
`ym` = `YYYY-MM`) are computed at insert time (via `datetime.isocalendar()`,
not `strftime` at query time) and stored as indexed columns so grouping is a
direct column scan with no runtime parsing.

The store is thread-safe (`check_same_thread=False`, WAL mode,
`busy_timeout=5000`) so it is safe from FastAPI's threadpool.

**Idempotent re-ingest:** when session data is re-extracted, `replace_source`
atomically deletes all records for that `source_id` then inserts the new set in
one transaction. A content-hash id means the same measurement maps to the same
row, so re-distilling a session never duplicates or orphans records.

### Confidence tiers

Confidence gates which records participate in compute by default. Three tiers:

| Tier | Value | Meaning |
|------|-------|---------|
| HIGH | `1.0` | Authored validators — the four derived count metrics plus `amount`/USD currency. Deterministic. |
| PROVISIONAL | `0.6` | Structurally-sane novel metric (finite number, unknown metric). Excluded by default. |
| UNVERIFIED | `0.3` | Fallback when no validator claims the record. Never silently summed. |

`COMPUTE_MIN_CONFIDENCE` (default `0.7`) sets the floor; only records at or
above that threshold enter aggregates. With the default threshold, only HIGH
records are summed. Lower tiers are never silently included — you must lower
the threshold explicitly to include PROVISIONAL records.

The confidence registry is a seam for a future teaching loop: product code can
register validators via `register_validator()` without touching engine source.

### Taught rules (durable confidence teaching)

Confidence validators can also be **taught and persisted** instead of only
registered in-process: `rules.db` stores declarative predicates (`metric` +
optional `unit` + optional `[value_min, value_max]` range → tier) that survive
a server restart. A rule promotes only — an unmatched rule abstains (returns
`0.0`), so `score_confidence`'s max-over-validators semantics are unchanged;
demotion is out of scope. At most one rule is active per
`owner + metric + unit`: adding a rule for a combination that already has an
active rule retires the prior one and bumps the version (an edit, not a
parallel rule) — history is preserved. `rules retire` soft-deletes a rule.
Adding or retiring a rule immediately re-scores that metric's existing
records (scoped to the changed metric only). See
[API_REFERENCE.md](API_REFERENCE.md#rules-endpoints) for the `/rules*`
endpoints and `brainpalace rules --help` for the CLI.

### Salience (write-time relevance)

Every record also carries a derived `salience` score (`0.0`-`1.0`), set at
write time via a `register_salience_scorer()` registry shaped like the
confidence registry (max over registered scorers). The seeded default is an
age-decay scorer: `0.5 ** (age_days / half_life)`, reusing
`BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS` (default `90.0`, the same knob that
drives retrieval time-decay ranking) — there is no separate salience knob, so
setting that half-life to `0` flattens default salience to `1.0` for every
record. A freshly written record has age≈0, so it scores ~1.0 under the
default scorer; the column only differentiates as records age, or immediately
after `brainpalace records recompute-salience` re-scores existing rows.
Unlike confidence validators (which see only a `RecordCandidate`), a salience
scorer receives the full `Record`, including `domain`/`source`, so a
domain-aware scorer is possible. No query mode reads `salience` in this
phase — the column is a seam for a future relevance-aware consumer.

## How records get populated

Records are extracted at the common session persist sink
(`SessionExtractService.store`) — the same code path reached by the plugin
SessionEnd flow and by `brainpalace extract-session`. Two kinds of records are
produced per session:

**Deterministic derived count records** — always HIGH confidence (`1.0`):

| Metric | What it counts |
|--------|----------------|
| `files_touched` | number of file entries in the extraction payload |
| `tools_used` | number of tool calls |
| `decisions` | number of decisions |
| `open_threads` | number of open threads |

These four derive from the extraction payload fields directly, so they need no
LLM and are always accurate.

**LLM-extracted numeric measurements** — the AI coding session is summarized
and any numeric measurements it mentions (e.g. `amount` in USD) are persisted
with `score_confidence`-determined confidence.

### Prerequisite: session extraction must be on

Records are persisted only when `extraction.mode != off`. With
`mode: subagent`, summaries are produced **inside Claude Code** (free on
the subscription model, no server-side metered cost) and posted to `/extract`,
which is when the server persists records. With `mode: off` (as in this repo),
no extraction runs and the record store stays empty.

See [SESSION_INDEXING.md](SESSION_INDEXING.md) for the full session extraction
guide.

## The compute query mode

### How to trigger it

Explicitly:

```bash
brainpalace query "how many files did I touch last week" --mode compute
brainpalace query "total tools used" --mode compute
brainpalace query "which week had the most decisions" --mode compute
```

**Auto-routing:** when `--mode hybrid` is in effect (the default) and the query
contains a compute-intent tell — `"how many"`, `"total"`, `"which week had the
most"`, etc. — the router tries compute first. If compute returns rows, those are
returned immediately. If compute returns empty (no metric resolves, store is
empty, or compute is disabled), the query falls back to `hybrid` retrieval as
usual. The auto-router never returns empty compute results as a final answer.

Auto-routing is deterministic (keyword tell-list only, no LLM).

### Supported operations and grouping

Supported aggregation operations: `sum`, `count`, `avg`, `max`, `min`.

Supported grouping keys:

| Group key | Column |
|-----------|--------|
| `week` | ISO week (`YYYY-Www`) |
| `month` | year-month (`YYYY-MM`) |
| `source` | source field |
| `subject` | subject field |
| `unit` | unit field |

Superlative queries ("which week had the most X") compile to a per-group sum
ordered descending with `LIMIT 1`.

### Determinism and idempotency

Compute results are fully deterministic — same records, same query, same result.
They depend only on the stored records and the `COMPUTE_MIN_CONFIDENCE` floor.
**Compute results are never cached** (the query cache does not apply).

### Privacy — session hard-off honored

Compute honors the same hard-off as session retrieval. When **session recall is
disabled** — session vector indexing is off, or session extraction is `mode: off`
(the two flags `session_recall_flags()` resolves, the same ones that hide session
chunks from search) — records with `source="session"` are excluded from every
aggregate. There is no per-query override. On this repo `extraction.mode:
off` already engages it, which is why `brainpalace status` reads *"Session Recall:
… disabled data hidden"*.

### `--json` response shape

Compute results arrive under the `compute` key, not `results`. `results` is
always `[]` for a compute response.

```json
{
  "results": [],
  "query_time_ms": 12.4,
  "total_results": 3,
  "compute": [
    {
      "label": "2026-W24",
      "value": 47.0,
      "metric": "files_touched",
      "op": "sum",
      "group": "2026-W24",
      "unit": null,
      "score": 1.0
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | human row label (e.g. `"2026-W24"` or `"files_touched sum"`) |
| `value` | float | aggregated value |
| `metric` | string | metric name |
| `op` | string | `sum` \| `count` \| `avg` \| `max` \| `min` |
| `group` | string or null | group key, or null if ungrouped |
| `unit` | string or null | unit if present on the records |
| `score` | float 0..1 | value normalised for display ordering only |

## Configuration

One flat knob in `Settings` (env var + runtime read), mirroring the graphrag
pattern:

Compute query mode has no switches — it is always selectable and returns empty
without records. Records are extracted automatically whenever session
extraction runs (gated by `extraction.mode`); there is no
record-extraction toggle. The only compute knob is the confidence floor.

| Env var | Default | Description |
|---------|---------|-------------|
| `COMPUTE_MIN_CONFIDENCE` | `0.7` | Floor for records entering aggregates (0..1) |

The `compute:` section in `.brainpalace/config.yaml` surfaces the same knob. An
absent key inherits the env/default value; the env var wins when both are set.

```yaml
compute:
  min_confidence: 0.7       # null = inherit
```

The dashboard surfaces this field via the config-reflection mechanism (same
pattern as `graphrag:`). The lifespan applies YAML overrides at startup.

## CLI

```bash
# Compute query
brainpalace query "how many files did I touch last week" --mode compute
brainpalace query "which week had the most tools used" --mode compute --json

# Record store management
brainpalace records stats                  # total, unverified, distinct metrics
brainpalace records stats --json
brainpalace records revalidate             # re-score all low-confidence records
brainpalace records revalidate --metric files_touched   # restrict to one metric
brainpalace records recompute-salience     # re-score all records' salience column
brainpalace records recompute-salience --metric weight  # restrict to one metric

# Taught confidence rules (durable, survive restart)
brainpalace rules add --metric weight --unit kg --min 30 --max 300 --tier HIGH
brainpalace rules list
brainpalace rules list --all               # include retired rules
brainpalace rules show <rule_id>
brainpalace rules retire <rule_id>
```

The query renderer prints `label: value` for compute rows; `--json` passes the
`compute` key through as-is.

## Server endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/records/stats` | Record store statistics |
| `POST` | `/records/revalidate` | Re-score low-confidence records |
| `POST` | `/records/recompute-salience` | Re-score the derived salience column |
| `GET` | `/rules?active=` | List taught confidence rules |
| `POST` | `/rules` | Teach a confidence rule |
| `GET` | `/rules/{rule_id}` | Get one taught rule |
| `POST` | `/rules/{rule_id}/retire` | Retire (soft-delete) a taught rule |

See [API_REFERENCE.md](API_REFERENCE.md#records-endpoints) and
[API_REFERENCE.md](API_REFERENCE.md#rules-endpoints) for full request and
response shapes.

## Status

`brainpalace status` includes a **Records / Compute** row showing total records,
unverified count, and the list of distinct metrics.

```
Records / Compute    0 (0 unverified) · metrics: none
```

When extraction is enabled and sessions are being summarized, this row fills in
over time as sessions complete.

## Implementation notes

- **SQLite only.** No Postgres Records store. Aggregation over typed columns does
  not benefit from pgvector; adding a Postgres dependency for records is not
  planned.
- **No new runtime dependencies.** `sqlite3` is Python stdlib. The Records
  subsystem adds zero new install dependencies.
- **Graph store unchanged.** `records.db` is a separate file; the existing graph
  store (`graph_store.db`) is unaffected.

## Related

- [SESSION_INDEXING.md](SESSION_INDEXING.md) — how records get populated (session extraction)
- [CONFIGURATION.md](CONFIGURATION.md#compute-configuration) — the compute config knob
- [API_REFERENCE.md](API_REFERENCE.md#records-endpoints) — endpoint reference
