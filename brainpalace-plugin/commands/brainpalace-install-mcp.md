---
name: brainpalace-install-mcp
description: Write BrainPalace's MCP server into the project's .mcp.json
parameters:
  - name: json
    type: bool
    required: false
    default: false
  - name: no-approve
    type: bool
    required: false
    default: false
  - name: scope
    type: choice
    required: false
    default: auto
skills:
  - using-brainpalace
last_validated: 2026-07-17
---

# BrainPalace Install MCP

## Purpose

Writes BrainPalace's MCP server into the project's `.mcp.json`, merging a single
`mcpServers.brainpalace` entry into any existing file and preserving every other
server already declared there (never clobbers `context7`, `supabase`, or any other
server the project already runs). Idempotent — re-running does not duplicate or
corrupt the file. `brainpalace init` runs this automatically (unless `--no-mcp`),
but `init` is not re-runnable on an already-initialized project without `--force`,
so this is the way for an existing project to adopt MCP.

`.mcp.json` is read only at session start, so a **newly written** entry does not
appear in the current session — restart Claude Code, and on a fresh or cloned
project approve the project's MCP servers in the trust dialog the first time (a
project starting untrusted cannot pre-approve its own servers). On a re-run that
finds the entry **already present**, the tools may already be loaded in your
session; the command says so conditionally rather than asserting either way.

## Usage

```
/brainpalace:brainpalace-install-mcp [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --json | No | false | Output as JSON |

## Execution

```bash
brainpalace install-mcp
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-init` | Initialize a project (writes .mcp.json by default) |
| `/brainpalace:brainpalace-doctor` | Diagnose your setup, incl. whether MCP is wired up |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --json | bool | false | Output as JSON. |
| --no-approve | bool | false | Declare the server in .mcp.json but do not approve it. Claude Code will hold it at 'Pending approval' until you approve it yourself. |
| --scope | choice | auto | How to grant the connection. 'local' registers with Claude Code's local scope (no approval, no folder trust). 'project' allowlists the .mcp.json entry instead (no `claude` CLI needed, but folder trust still applies). 'auto' uses local and falls back to project. |
<!--/GENERATED-->
