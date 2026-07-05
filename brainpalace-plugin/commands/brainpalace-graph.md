---
name: brainpalace-graph
description: Structural graph queries — shortest paths, impact analysis, and co-change
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-05
---

# BrainPalace Graph Queries

## Purpose

Answer structural questions the flat search modes cannot: how two code
entities are connected (`path`), what would be affected by changing one
(`impact`), and which files historically change together (`cochange`, from
git history). Nodes are referenced by canonical id (absolute path or
`path:fqname`) or a unique display name. These verbs read the SQLite graph
store directly — no chroma/vector backend requirement, and no embedding call.

## Usage

```
/brainpalace:brainpalace-graph <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|--------------|
| path | Shortest edge paths between two nodes (id or unique name) |
| impact | What transitively depends on a node (reverse dependency closure) |
| cochange | Files that historically change together with a file (git history) |

## Execution

```bash
brainpalace graph path <src> <dst> --json
brainpalace graph impact <node> --json
brainpalace graph cochange <file> --json
```

Examples:

```bash
brainpalace graph path api.py:handler lib.py:helper
brainpalace graph impact brainpalace_server/storage/graph_store.py --max-depth 2
brainpalace graph cochange brainpalace_server/storage/graph_store.py --min-shared 3
```

An ambiguous display name fails with the candidate ids listed; pass a node id
to disambiguate. `cochange` needs `git_indexing` enabled — an empty result
without it is expected, not an error.

## Output

On failure stdout is `{"error": ...}` with a non-zero exit — the same
contract as `query --json`. Human-readable output (no `--json`) prints one
line per path/dependent/co-changed file.

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-query` | Search with `--mode graph` for entity-relationship retrieval |
| `/brainpalace:brainpalace-status` | Check the server and graph index are healthy |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
<!--/GENERATED-->
