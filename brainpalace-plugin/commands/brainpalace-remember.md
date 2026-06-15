---
name: brainpalace-remember
description: Save a curated fact to the project's memory (BRAINPALACE_MEMORY.md)
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: tags
    type: text
    required: false
    default: 
  - name: section
    type: text
    required: false
    default: Notes
skills:
  - using-brainpalace
last_validated: 2026-06-15
---

# BrainPalace Remember

## Purpose

Saves a curated fact to the project's durable memory (`BRAINPALACE_MEMORY.md`).
Stored facts surface in the session-start context block and can be retrieved with
`brainpalace recall`.

## Usage

```
/brainpalace:brainpalace-remember "<text>" [--tags <tags>] [--section <section>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| TEXT | Yes | — | The fact to remember (positional) |
| --url | No | from config | BrainPalace server URL |
| --tags | No | "" | Comma-separated tags |
| --section | No | Notes | Markdown section to file the fact under |

## Execution

```bash
brainpalace remember "We deploy via GitHub Releases (OIDC), never poetry publish" --tags release
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-recall` | Recall curated memories matching a query |
| `/brainpalace:brainpalace-memories` | Manage the curated memory namespace |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config) |
| --tags | text |  | Comma-separated tags |
| --section | text | Notes | Markdown section to file under |
<!--/GENERATED-->
