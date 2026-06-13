---
name: brainpalace-help
description: Show available BrainPalace commands and usage
parameters:
  - name: command
    description: Specific command to get help for
    required: false
skills:
  - using-brainpalace
  - brainpalace-setup
last_validated: 2026-05-30
---

# BrainPalace Help

## Purpose

Displays available BrainPalace commands and usage information. Without parameters, shows a summary of all commands. With a specific command name, shows detailed help for that command.

## Usage

```
/brainpalace:brainpalace-help [--command <name>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --command | No | - | Specific command to get detailed help for |

### Examples

```
/brainpalace:brainpalace-help                        # Show all commands
/brainpalace:brainpalace-help --command search       # Detailed help for search
/brainpalace:brainpalace-help --command index        # Detailed help for index
```

## Execution

### Without Parameters: Show All Commands

Display the complete command reference:

```
BrainPalace Commands
====================

SEARCH COMMANDS
  brainpalace-search     Hybrid BM25+semantic search (recommended default)
  brainpalace-bm25       Pure BM25 keyword search for exact terms
  brainpalace-keyword    Alias for BM25 keyword search
  brainpalace-hybrid     Hybrid BM25+semantic with alpha tuning
  brainpalace-graph      GraphRAG relationship search (requires ENABLE_GRAPH_INDEX=true)

SETUP COMMANDS
  brainpalace-install    Install BrainPalace packages from PyPI
  brainpalace-config     View and manage provider configuration
  brainpalace-init       Initialize BrainPalace for current project

SERVER COMMANDS
  brainpalace-start      Start the BrainPalace server for this project
  brainpalace-stop       Stop the running server
  brainpalace-status     Show server status, port, and document count
  brainpalace-list       List all running BrainPalace instances

INDEXING COMMANDS
  brainpalace-index      Index documents for search
  brainpalace-inject     Index documents with content injection (scripts/metadata)
  brainpalace-folders    Manage indexed folders (list, add, remove)
  brainpalace-types      List available file type presets
  brainpalace-jobs       Monitor and manage async indexing jobs
  brainpalace-reset      Clear the document index (requires confirmation)

CACHE COMMANDS
  brainpalace-cache      View cache metrics or clear embedding cache

RUNTIME COMMANDS
  brainpalace-install-agent  Install plugin for a runtime (Claude, OpenCode, Gemini, Codex, skill-runtime)
  brainpalace-uninstall      Uninstall BrainPalace plugin files

HELP
  brainpalace-help       Show this help message

Use '/brainpalace:brainpalace-help --command <name>' for detailed help on any command.
```

### With --command Parameter: Show Detailed Help

Display detailed information for the specified command:

```bash
brainpalace <command> --help
```

**Example output for `/brainpalace:brainpalace-help --command search`:**

```
brainpalace-search
==================

Hybrid BM25+semantic search combining keyword matching with semantic similarity.
This is the recommended default search mode for most queries.

USAGE
  /brainpalace:brainpalace-search <query> [options]

PARAMETERS
  query       Required. The search query text.
  --top-k     Number of results (1-20). Default: 5
  --threshold Minimum relevance score (0.0-1.0). Default: 0.3
  --alpha     Hybrid blend (0=BM25, 1=semantic). Default: 0.5

EXAMPLES
  /brainpalace:brainpalace-search "authentication flow"
  /brainpalace:brainpalace-search "error handling" --top-k 10
  /brainpalace:brainpalace-search "OAuth" --alpha 0.3 --threshold 0.5

SEE ALSO
  brainpalace-semantic   For pure conceptual queries
  brainpalace-keyword    For exact term matching
```

## Output

### All Commands View

Format as grouped table:
- Group by category (Search, Setup, Server, Indexing, Help)
- Show command name and brief description
- Include footer with how to get detailed help

### Single Command View

Show comprehensive details:
- Full command name and description
- Usage syntax
- All parameters with types and defaults
- 2-3 practical examples
- Related commands (See Also)

## Command Reference

| Command | Category | Description |
|---------|----------|-------------|
| brainpalace-search | Search | Hybrid BM25+semantic search |
| brainpalace-bm25 | Search | Pure BM25 keyword search |
| brainpalace-keyword | Search | Alias for BM25 keyword search |
| brainpalace-hybrid | Search | Hybrid BM25+semantic with alpha tuning |
| brainpalace-graph | Search | GraphRAG relationship search* |
| brainpalace-install | Setup | Install packages from PyPI |
| brainpalace-config | Setup | View and manage provider configuration |
| brainpalace-init | Setup | Initialize for current project |
| brainpalace-embeddings | Setup | Configure embedding provider |
| brainpalace-start | Server | Start the server |
| brainpalace-stop | Server | Stop the server |
| brainpalace-status | Server | Show server status |
| brainpalace-list | Server | List all instances |
| brainpalace-index | Indexing | Index documents |
| brainpalace-inject | Indexing | Index with content injection |
| brainpalace-folders | Indexing | Manage indexed folders (list, add, remove) |
| brainpalace-types | Indexing | List file type presets |
| brainpalace-jobs | Indexing | Monitor and manage async jobs |
| brainpalace-reset | Indexing | Clear the index |
| brainpalace-cache | Cache | View cache metrics or clear embedding cache |
| brainpalace-install-agent | Runtime | Install plugin for Claude, OpenCode, Gemini, Codex, or skill-runtime |
| brainpalace-uninstall | Runtime | Uninstall BrainPalace plugin |
| brainpalace-help | Help | Show help |

*Graph search requires `ENABLE_GRAPH_INDEX=true` (disabled by default)

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Unknown command | Invalid command name specified | Check spelling, use `/brainpalace:brainpalace-help` for list |
| Command not found | Typo in command parameter | Refer to command reference table above |

## Notes

- All commands use the `brainpalace-` prefix
- Commands can be invoked as `/brainpalace:brainpalace-<name>` in Claude Code
- Setup commands are typically run once per project
- Search commands require a running server with indexed documents
- GraphRAG is enabled by default on new projects (`graphrag.enabled: true`). Disable with `export ENABLE_GRAPH_INDEX=false` or `graphrag.enabled: false` in config
