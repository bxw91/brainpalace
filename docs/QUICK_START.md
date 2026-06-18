---
last_validated: 2026-06-18
---

# BrainPalace Quick Start

Get up and running with BrainPalace in minutes. The Claude Code plugin is the primary interface - once installed, it handles everything else for you.

## Step 1: Install the Plugin

Install the BrainPalace plugin in Claude Code:

```bash
claude plugins install github:bxw91/brainpalace
```

This gives you access to 33 commands, 5 intelligent agents, and 2 skills for working with BrainPalace.

## Step 2: Install the Server and CLI

**Recommended (CLI + server in one shot):**

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
```

This installs `brainpalace-cli` via pipx; the CLI pulls the
`brainpalace-rag` server into the same venv. Verify with
`brainpalace --version`.

**Via the plugin** (does the same thing through Claude Code slash
commands):

```
/brainpalace-install
```

Installed packages:
- `brainpalace-cli` — command-line tool, primary entry point
- `brainpalace-rag` — FastAPI server for indexing + search

## Step 3: Configure API Keys

Configure your embedding and summarization providers:

```
/brainpalace-config
```

Choose from:
- **Cloud providers**: OpenAI, Anthropic, Cohere, Gemini, Grok
- **Local providers**: Ollama (fully offline mode)

Or use the complete setup wizard which handles installation AND configuration:

```
/brainpalace-setup
```

## Step 4: Initialize Your Project

Initialize BrainPalace for your current project:

```
/brainpalace-init
```

This creates a `.brainpalace/` directory with project-specific configuration.

## Step 5: Start the Server

Start the BrainPalace server:

```
/brainpalace-start
```

The server starts with automatic port allocation (no conflicts with other projects).

## Step 6: Index Your Documentation

Index your project's documentation and code:

```
/brainpalace-index ./docs
```

For code + documentation:

```
/brainpalace-index .
```

Use file type presets to index specific file categories:

```
/brainpalace-index ./src --include-type python
/brainpalace-index ./project --include-type python,docs
```

Manage indexed folders explicitly:

```
/brainpalace-folders add ./src
/brainpalace-folders add ./docs
/brainpalace-folders list
```

Check indexing status:

```
/brainpalace-status
```

## Step 7: Search Your Knowledge Base

Now you can search! Use the query command (hybrid mode by default):

```
/brainpalace-query "how does authentication work"
```

Or pick a specific search mode with `--mode`:

```
/brainpalace-query --mode vector "explain the architecture"
/brainpalace-query --mode bm25 "getUserById"
/brainpalace-query --mode graph "what calls AuthService"
```

---

## Step 8: Connect via MCP (optional)

Non-Claude-Code AI clients — VS Code native (GitHub Copilot agent mode),
Cursor, Kilo Code, Cline, Continue, Zed — can call BrainPalace through the
Model Context Protocol. BrainPalace ships an opt-in stdio shim:

```bash
brainpalace mcp --ensure-server   # auto-starts the HTTP server if not live
```

Clients spawn this as a child process and speak MCP over stdin/stdout. The
shim is a thin forwarder over the same REST endpoints used by the CLI; no
extra service to deploy. Per-client config snippets (and the VS Code
PATH-inheritance gotcha that bites Cursor too) live in
[`MCP_SETUP.md`](MCP_SETUP.md).

---

## Install for Other AI Runtimes

BrainPalace works with multiple AI coding assistants. Use `install-agent` to set up for your runtime:

```bash
brainpalace install-agent --agent codex
brainpalace install-agent --agent opencode
brainpalace install-agent --agent gemini
brainpalace install-agent --agent skill-runtime --dir ./my-skills
```

Preview what would be installed with `--dry-run`:

```bash
brainpalace install-agent --agent codex --dry-run
```

See the [User Guide](USER_GUIDE.md#runtime-installation) for full runtime installation details.

---

## All-in-One Setup

For the fastest setup, use the interactive wizard which does steps 2-6 automatically:

```
/brainpalace-setup
```

The Setup Assistant guides you through:
1. Installing packages
2. Configuring API keys
3. Initializing the project
4. Starting the server
5. Indexing your documentation

---

## Search Modes Quick Reference

| Command | Best For | Example |
|---------|----------|---------|
| `/brainpalace-query` | General questions | "how does caching work" |
| `/brainpalace-query --mode vector` | Conceptual queries | "explain the data flow" |
| `/brainpalace-query --mode bm25` | Exact terms, errors | "NullPointerException" |
| `/brainpalace-query --mode hybrid --alpha 0.7` | Fine-tuned search | "API authentication" |
| `/brainpalace-query --mode graph` | Dependencies | "what uses UserService" |
| `/brainpalace-query --mode multi` | Maximum recall | "everything about validation" |

---

## Using Agents for Complex Tasks

For complex research tasks, BrainPalace's intelligent agents help:

**You**: "Research how error handling is implemented across the codebase"

**Research Assistant** automatically:
1. Searches documentation for error handling patterns
2. Queries code for try/catch blocks and error classes
3. Uses graph mode to find error propagation
4. Synthesizes a comprehensive answer with file references

---

## Verify Your Setup

Check that everything is working:

```
/brainpalace-verify
```

This validates:
- Package installation
- API key configuration
- Server connectivity
- Index health

Or run the CLI diagnostic directly (works in scripts — exits non-zero on
any critical failure):

```bash
brainpalace doctor          # full report
brainpalace doctor --fix    # also apply safe, offline fixes
```

---

## Next Steps

- [User Guide](USER_GUIDE.md) - Detailed usage patterns
- [Plugin Guide](PLUGIN_GUIDE.md) - All 33 commands documented
- [Provider Configuration](../brainpalace-plugin/skills/using-brainpalace/references/provider-configuration.md) - Configure embedding and summarization providers
