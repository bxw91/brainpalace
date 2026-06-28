---
name: brainpalace-extraction
description: Graph-extraction drain queue (used by the AI drain command)
parameters:
last_validated: 2026-06-26
---

# BrainPalace Extraction

## Purpose

Provides direct access to the shared graph-extraction queue. Exposes three
subcommands: `pending` (fetches a bounded batch of items waiting for triplet
extraction from the server queue), `text` (fetches one pending doc chunk's text
by id), and `submit` (posts a completed extraction payload — doc triplets or
session extraction — back to the server).

The per-prompt drain is automatic (the `UserPromptSubmit` hook routes pending ids
to the `graph-triplet-extractor` / `chat-session-extractor` subagents, which use
the `extraction_fetch` / `extraction_submit` MCP tools). These subcommands are the
CLI surface of the same queue, for inspection and scripted/manual submits without
direct server API access.

## Usage

```
/brainpalace:brainpalace-extraction <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| pending | Print a bounded batch of pending extraction items as JSON |
| text | Print the text of one pending doc chunk by id as JSON |
| submit | Submit an extraction payload (doc triplets or session extraction) |

## Execution

```bash
brainpalace extraction pending
brainpalace extraction pending --limit 10
brainpalace extraction text <chunk_id>
brainpalace extraction submit --json payload.json
brainpalace extraction submit --json -   # read from stdin
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-status` | Check the server is healthy |
| `/brainpalace:brainpalace-query` | Search indexed documents |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
<!--/GENERATED-->
