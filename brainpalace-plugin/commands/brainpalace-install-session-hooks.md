---
name: brainpalace-install-session-hooks
description: Install BrainPalace's Claude Code SessionStart reminder hook
parameters:
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-15
---

# BrainPalace Install Session Hooks

## Purpose

Installs BrainPalace's Claude Code SessionStart reminder hook into `~/.claude/`
and prunes any old plugin-owned extraction hooks. The session-extraction hooks
themselves now ship with the Claude Code plugin, so this command only manages the
SessionStart reminder shim.

## Usage

```
/brainpalace:brainpalace-install-session-hooks [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --json | No | false | Output as JSON |

## Execution

```bash
brainpalace install-session-hooks
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-install-agent` | Install the plugin for a specific runtime |
| `/brainpalace:brainpalace-context` | Print the session-start context block |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --json | bool | false | Output as JSON. |
<!--/GENERATED-->
