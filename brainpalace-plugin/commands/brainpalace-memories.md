---
name: brainpalace-memories
description: Manage the curated memory namespace (list, show, delete, obsolete)
parameters:
skills:
  - using-brainpalace
last_validated: 2026-06-19
---

# BrainPalace Memories

## Purpose

Manages the curated memory namespace — durable facts saved with
`brainpalace remember`. This is a command group with subcommands for listing,
inspecting, and retiring individual memories.

## Usage

```
/brainpalace:brainpalace-memories <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| list | List curated memories |
| show | Show one memory by id |
| delete | Delete a memory by id |
| obsolete | Mark a memory obsolete (kept in the file, dropped from retrieval) |

## Execution

```bash
brainpalace memories list
brainpalace memories show <id>
brainpalace memories delete <id>
brainpalace memories obsolete <id>
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-remember` | Save a curated fact to project memory |
| `/brainpalace:brainpalace-recall` | Recall curated memories matching a query |
