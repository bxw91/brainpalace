---
name: brainpalace-context
description: Print the session-start context block (project facts + curated memory)
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-19
---

# BrainPalace Context

## Purpose

Prints the session-start context block for the current project: durable project
facts plus the curated memory namespace. It is designed to be run by a
SessionStart hook so the AI begins each session with the project's stable facts
already in context.

See `docs/SESSION_CONTEXT.md` for the full design.

## Usage

```
/brainpalace:brainpalace-context [--url <url>] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --url | No | from config | BrainPalace server URL |
| --json | No | false | Output the structured JSON block instead of text |

## Execution

```bash
brainpalace context
```

For machine consumption:

```bash
brainpalace context --json
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-remember` | Save a curated fact to project memory |
| `/brainpalace:brainpalace-recall` | Recall curated memories matching a query |
| `/brainpalace:brainpalace-memories` | Manage the curated memory namespace |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config) |
| --json | bool | false | Output the structured JSON |
<!--/GENERATED-->
