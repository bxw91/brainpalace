---
name: brainpalace-recall
description: Recall curated memories matching a query (memory namespace only)
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: top-k
    type: integer
    required: false
    default: 5
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-24
---

# BrainPalace Recall

## Purpose

Recalls curated memories matching a query. Unlike `query`, this searches only the
curated memory namespace (facts saved with `brainpalace remember`), not the
document index.

## Usage

```
/brainpalace:brainpalace-recall "<query text>" [--top-k <n>] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| QUERY_TEXT | Yes | — | The recall query (positional) |
| --url | No | from config | BrainPalace server URL |
| --top-k, -k | No | 5 | Number of memories to return |
| --json | No | false | Output as JSON |

## Execution

```bash
brainpalace recall "deployment process"
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-remember` | Save a curated fact to project memory |
| `/brainpalace:brainpalace-memories` | Manage the curated memory namespace |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config) |
| --top-k | integer | 5 | Number of memories to return |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->
