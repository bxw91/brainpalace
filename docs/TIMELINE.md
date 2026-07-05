---
last_validated: 2026-07-05
---

# Timeline query mode

`timeline` answers **"how did X evolve"** — it walks one entity's edge-validity
and supersession history in the knowledge graph to reconstruct how a belief or
fact changed over time. Retrieval and graph show what is *currently* true about
X; timeline shows *when* each fact was true and what replaced it.

## What it does

Given a query naming one entity with an explicit temporal/evolution marker
(`history of`, `timeline of`, `evolution of`, `how did X evolve`, `how has X
changed`, `X used to …`), timeline resolves the entity against graph node names
and returns its full ordered edge history — each edge with its `valid_from` /
`valid_until` and whether it is still valid.

Examples:
- `how did the auth decision evolve` → the decision's supersession chain.
- `history of auth.py` → when each of the file's relationships was true across
  re-indexes.

## Contracts

- **Graph-required:** timeline reads the knowledge graph; it is empty when
  `ENABLE_GRAPH_INDEX` is off or the graph is unbuilt (like `--mode graph`).
- **Entity resolution:** the named entity is resolved against graph node names,
  preferring an exact (case-insensitive) match and falling back to a substring
  match — name it as it appears in the graph (a file path, an entity name, a
  decision's text). A phrase matching no node is *unknown*, not *no history*, and
  falls back to normal retrieval. Pronoun/one-word subjects (e.g. "it used to …")
  do not resolve — name the entity explicitly.
- **Coverage (what is populated today):** timeline shows edge-validity
  transitions for *every* entity. `superseded-by` belief-chains exist for session
  **Decision** entities (the one write path that emits the history edge). The
  data-rich axes today are **file/code entities** (validity transitions from
  re-indexing) and **Decision entities** (supersession chains).
- **Full history:** timeline returns the entity's entire history (valid and
  invalidated edges), ordered by `valid_from, id` — deterministic, oldest first.
- **Retained-corpus:** answers are over the retained graph; eviction/sweeps shift
  results.

## Usage

    brainpalace query "how did the auth decision evolve" --mode timeline
    brainpalace query "history of auth.py" --mode timeline --json

`--json` emits a `timeline` array of `{subject, predicate, object, valid_from,
valid_until, valid, score}`. Auto-routing: a `--mode hybrid` query carrying a
temporal/evolution marker is tried as timeline after compute, scan, and absence;
empty falls back to hybrid.

## Design note — CO-2 (edge-only rule)

Timeline is built on the existing edge-validity machinery: every mutable fact is
modeled as an edge with `valid_from`/`valid_until`. No node-level validity columns
were added (CO-2 decided (a), the edge-only rule) — the machinery already exists
and is populated, and no Phase-4 query needs node columns.
