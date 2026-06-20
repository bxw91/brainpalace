---
name: brainpalace-read-only
description: Enable/disable read-only mode (disables embedding, summarization, writes)
parameters:
skills:
  - using-brainpalace
last_validated: 2026-06-19
---

# BrainPalace Read-Only

## Purpose

Enables or disables read-only mode for the server. In read-only mode the server
disables embedding, summarization, and all writes — useful for serving an
existing index without incurring provider cost or mutating data.

The mode argument is positional: `on`, `off`, or `status`.

## Usage

```
/brainpalace:brainpalace-read-only {on|off|status}
```

### Arguments

| Argument | Description |
|----------|-------------|
| on | Enable read-only mode |
| off | Disable read-only mode |
| status | Report the current read-only state |

## Execution

```bash
brainpalace read-only status
brainpalace read-only on
brainpalace read-only off
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-status` | Check server status and health |
| `/brainpalace:brainpalace-config` | View and manage configuration |
