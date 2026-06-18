---
last_validated: 2026-06-18
---

# Session Knowledge-Graph Taxonomy

How BrainPalace turns AI-coding sessions into a typed, queryable knowledge
graph (Phase 100). This complements the code/doc/infra entity graph
([GRAPHRAG_GUIDE](GRAPHRAG_GUIDE.md)) with **session memory** entities mined
from extracted sessions.

## Where it comes from

1. A session is extracted (manually via `/brainpalace-extract-session`, or
   automatically via the SessionEnd → SessionStart subagent) into a strict JSON
   payload. See [SESSION_INDEXING](SESSION_INDEXING.md).
2. The payload's `triplets[]` (closed vocabulary) are persisted into the graph
   by `POST /sessions/extract` via `add_triplet`.
3. **Node types are derived server-side from the relation** — the wire schema
   carries no per-triplet types, so the extractor prompt stays simple and the
   020 contract stays frozen. The mapping lives in
   `services/session_triplet_types.py`.

## Entity types

| Type | Represents |
|------|------------|
| `Decision` | A choice made during a session |
| `Error` | An error/bug encountered |
| `Session` | An AI-coding session |
| `Tool` | A tool/command run in a session |
| `File` | A file edited / created / read |
| `Task` | A task or phase of work |

These join the existing 17 code/doc/infra types in `models/graph.py`, so
`brainpalace query -m graph` and type-filtered queries (`query_by_type`)
recognise them.

## Relations (closed vocabulary)

Direction is **subject → object**. Source of truth is the extractor prompt
(070 command / 080 subagent); this table is what the server types each end as.

| Relation | Meaning (subject → object) | subject_type | object_type |
|----------|----------------------------|--------------|-------------|
| `touches` | edited/created file → the thing it implements | `File` | *(untyped — free-text concept)* |
| `fixed-by` | error/bug → the fix/decision that resolves it | `Error` | `Decision` |
| `superseded-by` | older decision → the newer one that replaces it | `Decision` | `Decision` |
| `ran-in` | tool/command → the session it ran in | `Tool` | `Session` |
| `depends-on` | task/phase → its prerequisite | `Task` | `Task` |
| `decided` | actor/session → a decision it made | `Session` | `Decision` |

**`A superseded-by B` means B replaces A.** Ambiguous endpoints (the object of
`touches`) are deliberately left **untyped** (`None` → the graph store's
`"Entity"` label) rather than guessed.

## Composing with temporal validity (Phase 090)

On the `sqlite` backend, edges carry `valid_from` / `valid_until`. The session
graph uses this for decision history:

- A `superseded-by` edge marks that the **older** decision is no longer current.
- `timeline(<decision>)` returns every edge touching a decision ordered by
  validity start — the substrate for "show me how this decision evolved".

## Cross-session linking (Phase 140)

When `/sessions/extract` persists a session, a linking pass runs (best-effort;
**full effect requires the `sqlite` backend** — temporal ops no-op on `simple`):

- **Canonicalisation.** File-like triplet endpoints are normalised to
  project-root-relative POSIX paths *before* `add_triplet`, so `auth.py`,
  `./auth.py`, and `/abs/proj/auth.py` collapse to **one** `File` node. Non-path
  entities are left untouched.
- **Supersession.** For each decision that `supersedes` a prior one (or each
  `superseded-by` triplet), the prior `Decision` node is resolved (exact
  normalised-text match — conservative, never substring) and its still-valid
  *facts* (`touches`, `decided`, …) are `invalidate()`d so stale advice drops out
  of default queries. The `superseded-by` edge itself is **preserved** so
  `as_of` / `timeline` still reconstruct the full chain.
- **Promotion.** Durable, rationale-backed current decisions are promoted into
  the [curated-memory namespace](MEMORY.md) (`BRAINPALACE_PROMOTE_DECISIONS`,
  default on), closing the sessions → curated-memory loop.
- **Stale-decision penalty.** At query time, `session_decision` results whose
  decision is the subject of a valid `superseded-by` edge are down-ranked by
  `BRAINPALACE_STALE_DECISION_PENALTY` (default 0.5; 1.0 = off).

## Backward compatibility

Sessions extracted before Phase 100 stored untyped nodes (label `"Entity"`).
They keep working; re-extracting a session upgrades its nodes to typed ones. No
migration is required.
