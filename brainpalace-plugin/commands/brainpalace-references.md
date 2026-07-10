---
name: brainpalace-references
description: Search and manage the lazy-tier reference catalog — list, semantic search, resolve, and backfill embeddings
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-10
---

# BrainPalace References

## Purpose

Searches and manages the lazy-tier reference catalog — pointer + summary
entries for sources fetched-and-extracted on demand. Exposes four subcommands:
`list` (all references, optionally filtered by domain), `search` (semantic
search over reference summaries, embedding the query server-side), `resolve`
(print the stored pointer and summary for a reference id), and `embed-missing`
(backfill embeddings for references that lack one, making them searchable).

References marked with a non-`normal` sensitivity are hidden from search by
default; pass `--include-sensitive` to reveal them (interactive CLI only).

## Usage

```
/brainpalace:brainpalace-references <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| list | List references, optionally filtered by `--domain` |
| search | Semantic search over reference summaries for a query |
| resolve | Print the stored pointer + summary for a reference id |
| embed-missing | Backfill embeddings for references that lack one |

## Execution

```bash
brainpalace references list
brainpalace references list --domain glasses
brainpalace references search "power bill"
brainpalace references search "private note" --include-sensitive
brainpalace references resolve abc123
brainpalace references embed-missing
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-ingest` | Ingest a resolved reference's body as searchable text |
| `/brainpalace:brainpalace-query` | Search indexed documents (references surface in hybrid results) |
| `/brainpalace:brainpalace-status` | Check the server is healthy |

### Flags
<!--GENERATED:flags-->
_This command takes no top-level flags._
<!--/GENERATED-->
