---
name: brainpalace-mcp
description: Serve BrainPalace over stdio for MCP-aware AI clients
parameters:
  - name: ensure-server
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-24
---

# BrainPalace MCP

## Purpose

Starts an MCP (Model Context Protocol) server over stdio. The MCP shim is a thin
wrapper around the existing BrainPalace HTTP server's REST endpoints, so the HTTP
server must already be running for tool calls to succeed. Pass `--ensure-server`
to have the shim start one on boot if discovery finds none.

See `docs/MCP_SETUP.md` for client configuration.

## Usage

```
/brainpalace:brainpalace-mcp [--ensure-server]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --ensure-server | No | false | Start a BrainPalace HTTP server for the spawn-time CWD project if none is live. Recommended for every non-Claude-Code client |

## Execution

```bash
brainpalace mcp
```

For non-Claude-Code clients that may not have a server running:

```bash
brainpalace mcp --ensure-server
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-start` | Start the HTTP server |
| `/brainpalace:brainpalace-status` | Check server status |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --ensure-server | bool | false | If no BrainPalace HTTP server is live for the spawn-time CWD project, start one before serving MCP. Recommended for every non-Claude-Code client (see Phase Q Task 5.5). |
<!--/GENERATED-->

## MCP Tools
<!--GENERATED:mcp-tools-->
| Tool | Description |
|------|-------------|
| `ai_guide` |  |
| `extraction_fetch` |  |
| `extraction_submit` |  |
| `folders_list` |  |
| `jobs_approve` |  |
| `jobs_list` |  |
| `memorize` |  |
| `query` |  |
| `recall` |  |
| `session_context` |  |
| `status` |  |
| `whoami` |  |
<!--/GENERATED-->
