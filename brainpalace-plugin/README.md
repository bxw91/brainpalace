---
last_validated: 2026-06-18
---

# BrainPalace Plugin

A Claude Code plugin for document search with hybrid BM25/semantic retrieval. Index your documentation and source code, then search using keyword matching, semantic similarity, or combined hybrid mode.

## Features

- **Hybrid Search**: Combines BM25 keyword matching with semantic vector search for best results
- **Three Search Modes**: BM25 (fast keywords), Vector (semantic), Hybrid (combined)
- **Multi-Instance**: Run separate servers for different projects with automatic port allocation
- **Code Search**: AST-aware indexing for Python, TypeScript, JavaScript, Java, Go, Rust, C, C++

## Installation

### 1. Install Claude Code Plugin

```bash
# From GitHub
claude plugins install github:bxw91/brainpalace
```

### 2. Install BrainPalace Packages

```bash
pip install brainpalace-rag brainpalace-cli
```

### 3. Configure API Key

```bash
export OPENAI_API_KEY="sk-proj-..."
```

### 4. Initialize and Start

```bash
brainpalace init
brainpalace start
brainpalace index /path/to/docs
```

## Quick Start

Once installed, use these slash commands in Claude Code:

```
/brainpalace-query "authentication flow"                 # Hybrid search (default)
/brainpalace-query "how does auth work" --mode vector    # Conceptual search
/brainpalace-query "AuthenticationError" --mode bm25     # Exact term search
```

## Commands

### Search Command
All retrieval is one command, `/brainpalace-query`, with a `--mode` flag:

| Mode flag | Description |
|-----------|-------------|
| `/brainpalace-query` (default `--mode hybrid`) | Hybrid search (BM25 + semantic) |
| `/brainpalace-query --mode vector` | Semantic vector search |
| `/brainpalace-query --mode bm25` | BM25 keyword search |
| `/brainpalace-query --mode graph` | Knowledge-graph relationships |
| `/brainpalace-query --mode multi` | Fusion of all modes |

### Setup Commands
| Command | Description |
|---------|-------------|
| `/brainpalace-install` | Install pip packages |
| `/brainpalace-setup` | Complete guided setup |
| `/brainpalace-config` | Configure API keys |
| `/brainpalace-init` | Initialize project |
| `/brainpalace-verify` | Verify installation |

### Server Commands
| Command | Description |
|---------|-------------|
| `/brainpalace-start` | Start server (auto-port) |
| `/brainpalace-stop` | Stop server |
| `/brainpalace-status` | Show server health |
| `/brainpalace-list` | List all instances |

### Indexing Commands
| Command | Description |
|---------|-------------|
| `/brainpalace-index` | Index documents |
| `/brainpalace-reset` | Clear all indexed content |

## Search Modes

| Mode | Speed | Best For | Example Query |
|------|-------|----------|---------------|
| `hybrid` | Slower | General queries | "OAuth implementation guide" |
| `bm25` | Fast | Technical terms, function names | "AuthenticationError" |
| `vector` | Slower | Concepts, explanations | "how does authentication work" |

## Requirements

- Python 3.10+
- OpenAI API key (for vector/hybrid search)
- Optional: Anthropic API key (for code summarization)

## Skills

This plugin includes two skills:

1. **using-brainpalace**: Search mode guidance and API reference
2. **configuring-brainpalace**: Installation, configuration, and troubleshooting

## Optional: Conditional SessionStart Reminder

Want Claude Code to be reminded at session start to prefer `brainpalace query` over Glob/Grep — but **only in projects that are actually indexed**?

This plugin ships a conditional SessionStart hook template that gates the reminder on `brainpalace whoami` exit code, so non-indexed projects are never forced to use BrainPalace.

```bash
# Copy the template
cp <plugin-install-dir>/hooks/sessionstart-hook.sh \
   ~/.claude/hooks/brainpalace-sessionstart.sh
chmod +x ~/.claude/hooks/brainpalace-sessionstart.sh
```

Then add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/brainpalace-sessionstart.sh",
            "timeout": 3
          }
        ]
      }
    ]
  }
}
```

Restart Claude Code. The reminder will now fire only in projects with a `.brainpalace/` index. In non-indexed projects, the hook silently no-ops and the AI uses native search tools.

See `hooks/sessionstart-hook.sh` for full inline documentation.

## License

MIT

## Support

- Issues: https://github.com/bxw91/brainpalace/issues
- Documentation: See `skills/` folder for detailed guides
