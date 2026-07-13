---
last_validated: 2026-07-13
---

# Absence Mode — anti-join over your typed records

`--mode absence` answers **"which subjects appear under one partition value but
never under another"** — the anti-join / "planned but never implemented" class —
over the typed records store. Deterministic set-differencing over indexed
columns: no LLM, no embeddings, no network, no cost.

## How it works

1. The compiler splits the query on a negation-of-counterpart phrase (`but
   not`, `but not in`, `but never`, `without`, `missing from`, `absent from`,
   `not in`) and
   resolves each side against the store's *live vocabulary* of `metric`,
   `source`, and `domain` values — never a value that isn't actually stored.
   Both sides must resolve in the **same** partition column, or the compiler
   returns no plan (never guesses).
2. The executor anti-joins the records table on `subject`: rows present where
   `partition = present_in` (confidence-gated) but absent where
   `partition = absent_from` (confidence-gated).
3. Rows come back as the missing `subject`s, alphabetically.

Examples:
- `distance but not duration` → subjects measured for distance, never duration.
- `discussed in gmail but not session` (once multiple sources exist).

## Scope and contract

- **Stored-vocabulary only.** Absence compares values that exist in the
  records store. A value never recorded is *unknown*, not *absent* — free-text
  framings whose words are not stored values (e.g. literal
  "planned"/"implemented") do not compile and fall back to normal retrieval.
- **Confidence.** HIGH-only by default (confidence ≥ 0.7) on both sides — a
  low-confidence row neither creates nor fills a gap.
- **Live-store snapshot.** Answers reflect whatever the records store
  currently holds — there is no retention/eviction of records today, so
  results are a snapshot of the current store, not a class distinction.
- **Single-source today.** The records store currently holds one
  `(domain=chat-life, source=session)` partition, so `source`/`domain`
  partitions return nothing until federation adapters add other sources;
  `metric` is the axis with real data today.

## Routing

Explicit: `--mode absence`. Automatic: hybrid queries carrying an absence tell
try absence **after** compute and scan — a query that also carries a compute
or scan tell routes there instead (e.g. "how many subjects have distance but
not duration" → compute; "what did I discuss in gmail but not session" → scan,
because it carries the scan tell "did i discuss"). Empty absence falls back to
normal retrieval.

## CLI

```bash
brainpalace query "distance but not duration" --mode absence
brainpalace query "distance but not duration" --mode absence --json
```

**`--json` contract for absence:** `results` is always `[]`; rows live under
`absence`. Each row: `label` (the missing subject), `present_in` (partition
value it IS under), `absent_from` (partition value it is MISSING from),
`partition` (`metric`/`source`/`domain`), `score` (reserved, always `0.0`).

## Configuration

Absence has no switches — it is always selectable and returns empty without
qualifying records. It reuses `compute.min_confidence` for the confidence gate.
