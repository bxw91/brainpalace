---
last_validated: 2026-07-13
---

# Scan Mode — deterministic term counts over your session history

`--mode scan` answers "which week did I say word X most" — occurrence counts
of a term or quoted phrase over the **archived session transcripts**, bucketed
by ISO week, month, day, or source tool. Deterministic map-reduce: no LLM, no
embeddings, no network, no cost.

## How it works

1. The compiler extracts ONE term from the query — a quoted phrase
   (`"entity resolution"`) or the word after mention/say/discuss/talk-about
   tells. Under an **explicit** `--mode scan` a bare single-word query is also
   taken as the term (so `scan profile` == `scan "profile"`); a bare multi-word
   query stays ambiguous. No term → scan returns nothing (never guesses). The
   **auto-router** keeps the strict contract — it never turns a bare word into a
   scan term, so plain hybrid queries are unaffected.
2. The executor walks the session archive
   (`.brainpalace/session_archive/YYYY-MM-DD-<tool>/*.jsonl`), parses each
   transcript through the standard session loader, tokenizes conversational
   text turns with the same per-language analyzers BM25 uses, and counts
   non-overlapping occurrences of the tokenized term.
3. Rows come back per bucket, ordered by count.

## Scope and contract

- **Corpus = the retained archive.** Scan reads what the session-archive
  feature has kept. Archive off ⇒ scan is empty. Retention pruning shifts
  answers — a scan result is a statement about the archive, not about all of
  history.
- **Time-stamped sources only.** Buckets come from the archive's day folders.
- **Raw transcripts, both roles.** Counts include your own prompts and the
  assistant's replies (conversational text turns only — tool calls/results
  and thinking are excluded).
- **Tokenized matching.** "deploy" matches "Deploy" and (with the stemming
  engine) close inflections; it does not substring-match inside other words.

## Routing

Explicit: `--mode scan`. Automatic: hybrid queries with utterance-history
tells ("did I mention", "how many times did I say", "which week did I …")
try scan after compute. Tie-break with compute: **a typed record metric that
resolves wins (compute); otherwise scan.** Empty scan falls back to normal
retrieval.

## CLI

```bash
brainpalace query "which week did I mention foobar most" --mode scan
brainpalace query 'how often did I say "entity resolution" per month' --mode scan --json
```

**`--json` contract for scan:** `results` is always `[]`; rows live under
`scan`. Each row: `label` (bucket key or `"<term> count"`), `value` (float
count), `term`, `group` (bucket key or `null`), `score` (0..1 normalised).

## Configuration

Scan has no switches — it is always selectable and returns empty without an
archive. The archive itself is governed by the session-archive settings (see
`docs/SESSION_INDEXING.md`); `SESSION_ARCHIVE_ENABLED=false` disables both
archiving and scan.
