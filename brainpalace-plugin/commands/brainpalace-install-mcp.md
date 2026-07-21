---
name: brainpalace-install-mcp
description: Write BrainPalace's MCP server into an MCP client's config file
parameters:
  - name: json
    type: bool
    required: false
    default: false
  - name: no-approve
    type: bool
    required: false
    default: false
  - name: client
    type: choice
    required: false
    default: claude
  - name: scope
    type: choice
    required: false
    default: ""
skills:
  - using-brainpalace
last_validated: 2026-07-21
---

# BrainPalace Install MCP

## Purpose

With the default `--client claude` (unchanged), writes BrainPalace's MCP server
into the project's `.mcp.json`, merging a single `mcpServers.brainpalace` entry
into any existing file and preserving every other server already declared there
(never clobbers `context7`, `supabase`, or any other server the project already
runs). Idempotent — re-running does not duplicate or corrupt the file.
`brainpalace init` runs this automatically (unless `--no-mcp`), but `init` is
not re-runnable on an already-initialized project without `--force`, so this is
the way for an existing project to adopt MCP.

`.mcp.json` is read only at session start, so a **newly written** entry does not
appear in the current session — restart Claude Code, and on a fresh or cloned
project approve the project's MCP servers in the trust dialog the first time (a
project starting untrusted cannot pre-approve its own servers). On a re-run that
finds the entry **already present**, the tools may already be loaded in your
session; the command says so conditionally rather than asserting either way.

With any other `--client` (`cursor`, `windsurf`, `vscode`, `kilo`, `cline`,
`qwen`, `kimi`), writes/merges the server into that editor's own MCP config file
instead — no Claude-specific approval step, since these clients trust their own
config file. `--scope` picks `project` or `global` (defaulting to the client's
usual location: global for Cursor/Windsurf/Kimi, project for VS Code/Kilo/
Cline/Qwen). A JSONC file (VS Code, Kilo) that already has comments is never
rewritten — the exact snippet to paste in by hand is printed instead, so your
comments are never corrupted. Cline's config lives inside a VS Code extension's
storage; if that extension isn't installed, the snippet is printed instead of
fabricating its directory. See [docs/MCP_SETUP.md](../../docs/MCP_SETUP.md) for
every client's exact config shape.

## Usage

```
/brainpalace:brainpalace-install-mcp [--json] [--client <name>] [--scope <scope>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --json | No | false | Output as JSON |
| --client | No | claude | Target MCP client: claude, cursor, windsurf, vscode, kilo, cline, qwen, kimi |
| --scope | No | (per-client) | claude: auto/local/project. Other clients: project/global |

## Execution

```bash
brainpalace install-mcp
brainpalace install-mcp --client cursor
brainpalace install-mcp --client vscode --scope project
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
| --no-approve | bool | false | Claude only: declare the server in .mcp.json but do not approve it. Claude Code will hold it at 'Pending approval' until you approve it yourself. |
| --client | choice | claude | Target MCP client to write the server entry for. |
| --scope | choice | "" | For --client claude: 'auto' (default), 'local', or 'project' — see below. For every other --client: 'project' or 'global', defaulting to that client's usual config location. |
<!--/GENERATED-->
