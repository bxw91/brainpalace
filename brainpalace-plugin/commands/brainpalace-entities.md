---
name: brainpalace-entities
description: Manage identity — person / alias / link, plus deterministic candidate resolution (who someone is)
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-11
---

# BrainPalace Entities

## Purpose

Give a multi-source consumer a first-class home for *who someone is*. The
engine stores `person` rows (a null name IS the "unknown person"), scoped and
time-bounded `alias` bindings (`"Mama"` means a different person for a different
speaker), and `link` rows attaching a chunk / session / span — or an opaque
external key like a voice cluster — to a person. Exposes six subcommands:
`person` (upsert), `alias` (bind a surface to a person), `link` (attach a ref or
record it unresolved), `resolve` (ranked candidates + evidence), `unresolved`
(the bucket of links with no person yet), and `backfill` (re-score unresolved
links against the current aliases).

The engine only ranks — it **never picks a winner**. `resolve` returns a scored
candidate list with evidence; the margin threshold and the decision live in the
consumer app. Identity is user-asserted ground truth in its own store, never a
rebuildable cache, and it is never read back out of the knowledge graph.

Non-`normal`-sensitivity persons are hidden from default person-filtered
queries, matching the chunk-level default-deny.

## Usage

```
/brainpalace:brainpalace-entities <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| person | Upsert a person (naming an unknown one is an update in place) |
| alias | Bind a surface to a person (scoped + time-bounded) |
| link | Attach a ref to a person, or record it unresolved |
| resolve | Ranked candidates + evidence — never picks a winner |
| unresolved | List unresolved links (the bucket the app decides or asks about) |
| backfill | Re-score unresolved links against the current aliases |

## Execution

```bash
brainpalace entities person --domain home --name Ana
brainpalace entities alias --surface Mama --person-id <pid> --scope <speaker-pid>
brainpalace entities link --ref "msg_1#0" --ref-kind span --role mentioned \
  --method alias_match --at 2026-07-09T00:00:00Z --surface Mama
brainpalace entities resolve --surface Mama --scope <speaker-pid> --json
brainpalace entities unresolved --json
brainpalace entities backfill
```

## Output

On failure stdout is `{"error": ...}` with a non-zero exit — the same contract
as `query --json`. On success the result object is printed (the person id, the
ranked candidate list, or the unresolved bucket).

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-ingest` | Ingest the text a link addresses (links need a chunk that already exists) |
| `/brainpalace:brainpalace-query` | Search indexed documents; person-filtered results group by person |
| `/brainpalace:brainpalace-status` | Check the server is healthy |

### Flags
<!--GENERATED:flags-->
_This command takes no top-level flags._
<!--/GENERATED-->
