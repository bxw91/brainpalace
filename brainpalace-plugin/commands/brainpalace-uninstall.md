---
name: brainpalace-uninstall
description: Uninstall BrainPalace (guided teardown, or global-only with --yes/--json)
parameters:
  - name: "yes"
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-15
---

# BrainPalace Uninstall

## Purpose

Uninstalls BrainPalace. Run with no flags for a guided teardown that confirms each
step: stop servers, remove plugin dirs, strip MCP entries, delete per-project and
global state, then print the leftover optional/manual steps (the package
uninstall for pip installs, the Claude-Code-managed marketplace plugin, and your
shell-rc API key).

With `--yes` / `--json` it stays non-interactive and removes only the global data
(XDG + legacy dirs) and stops servers — it does NOT remove project-level
`.brainpalace/` dirs.

## Usage

```
/brainpalace:brainpalace-uninstall [--yes] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --yes, -y | No | false | Skip confirmation prompt; non-interactive, global data only |
| --json | No | false | Output as JSON; non-interactive, global data only |

## Execution

```bash
brainpalace uninstall           # Guided teardown (recommended)
brainpalace uninstall --yes     # Non-interactive: global data only
brainpalace uninstall --json    # Machine output: global data only
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-update` | Upgrade BrainPalace to the latest version |
| `/brainpalace:brainpalace-plugin` | Inspect plugin installation status |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --yes | bool | false | Skip confirmation prompt |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->
