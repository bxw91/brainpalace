---
name: brainpalace-plugin
description: Inspect the BrainPalace Claude Code plugin (installation status)
parameters:
skills:
  - using-brainpalace
last_validated: 2026-06-24
---

# BrainPalace Plugin

## Purpose

Inspects the BrainPalace Claude Code plugin. This is a command group; the
`status` subcommand reports whether the plugin is installed.

## Usage

```
/brainpalace:brainpalace-plugin <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| status | Report whether the BrainPalace Claude Code plugin is installed |

## Execution

```bash
brainpalace plugin status
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-install-agent` | Install the plugin for a specific runtime |
| `/brainpalace:brainpalace-uninstall` | Uninstall BrainPalace |
