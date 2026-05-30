---
last_validated: 2026-05-23
---

# BrainPalace Plugin Guide

Complete reference for the BrainPalace Claude Code plugin - 30 commands, 3 agents, and 2 skills for intelligent document and code search.

## Table of Contents

- [Installation](#installation)
- [Quick Setup](#quick-setup)
- [Search Commands](#search-commands)
- [Server Commands](#server-commands)
- [Index Management Commands](#index-management-commands)
- [Setup Commands](#setup-commands)
- [Provider Commands](#provider-commands)
- [Intelligent Agents](#intelligent-agents)
- [Skills](#skills)
- [Search Modes](#search-modes)
- [Provider Configuration](#provider-configuration)
- [Integration Patterns](#integration-patterns)
- [Troubleshooting](#troubleshooting)

---

## Installation

Install the BrainPalace plugin in Claude Code:

```bash
claude plugins install github:bxw91/brainpalace
```

This provides:
- **30 slash commands** for all operations
- **3 intelligent agents** for complex tasks
- **2 skills** for context-aware assistance

### SessionStart hook

The plugin ships a SessionStart hook
(`brainpalace-plugin/templates/sessionstart-hook.sh`) that emits a context
reminder (and, when enabled, an injected project-context block) when Claude
Code opens a directory that has a `.brainpalace/` index.

---

## Quick Setup

The fastest way to get started:

```
/brainpalace-setup
```

This interactive wizard:
1. Installs packages (`brainpalace-rag`, `brainpalace-cli`)
2. Configures API keys
3. Initializes your project
4. Starts the server
5. Indexes your documentation

Or step-by-step:

```
/brainpalace-install     # Install packages
/brainpalace-providers   # Configure API keys
/brainpalace-init        # Initialize project
/brainpalace-start       # Start server
/brainpalace-index .     # Index documents
```

---

## MCP integration (opt-in)

The plugin's primary integration is the **skill + slash commands** documented
below. Claude Code users who prefer typed MCP tool calls instead can wire the
opt-in MCP server via the copy-paste snippet shipped at
[`templates/mcp-config-claude-code.json`](../brainpalace-plugin/templates/mcp-config-claude-code.json).
Full per-client setup (Claude Code, VS Code native / GitHub Copilot, Cursor,
Kilo Code, Cline, Continue, Zed) lives in [`MCP_SETUP.md`](MCP_SETUP.md).
Non-Claude-Code clients should add `--ensure-server` to the command line so
the shim auto-starts the HTTP server for the workspace project — Claude
Code's own start hook covers that case.

---

## Search Commands

### `/brainpalace-search`

Smart hybrid search - the recommended default for general questions.

```
/brainpalace-search "how does authentication work"
/brainpalace-search "error handling patterns" --top-k 10
```

### `/brainpalace-semantic`

Pure vector/semantic search for conceptual queries.

```
/brainpalace-semantic "explain the overall architecture"
/brainpalace-semantic "what is the purpose of this module"
```

### `/brainpalace-keyword`

BM25 keyword search for exact terms, function names, error codes.

```
/brainpalace-keyword "NullPointerException"
/brainpalace-keyword "getUserById"
```

### `/brainpalace-bm25`

Alias for keyword search.

```
/brainpalace-bm25 "AuthenticationError"
```

### `/brainpalace-vector`

Alias for semantic search.

```
/brainpalace-vector "how does caching improve performance"
```

### `/brainpalace-hybrid`

Hybrid search with explicit alpha control.

```
/brainpalace-hybrid "OAuth implementation" --alpha 0.7
/brainpalace-hybrid "database connection" --alpha 0.3
```

**Alpha Parameter:**
- `1.0` = Pure semantic search
- `0.5` = Balanced (default)
- `0.0` = Pure keyword search

### `/brainpalace-graph`

Knowledge graph search for relationships and dependencies.

```
/brainpalace-graph "what calls AuthService"
/brainpalace-graph "classes that extend BaseController"
/brainpalace-graph "modules that import jwt"
```

### `/brainpalace-multi`

All modes combined with Reciprocal Rank Fusion for maximum recall.

```
/brainpalace-multi "complete authentication flow"
/brainpalace-multi "everything about data validation"
```

### Common Search Options

All search commands support:

| Option | Default | Description |
|--------|---------|-------------|
| `--top-k` | 5 | Number of results |
| `--threshold` | 0.7 | Minimum similarity (0.0-1.0) |
| `--source-types` | all | Filter: doc, code, or both |
| `--languages` | all | Filter by programming language |
| `--scores` | false | Show component scores |

---

## Server Commands

### `/brainpalace-start`

Start the BrainPalace server with automatic port allocation.

```
/brainpalace-start
/brainpalace-start --port 8080
```

### `/brainpalace-stop`

Stop the running server.

```
/brainpalace-stop
```

### `/brainpalace-status`

Check server health and document count.

```
/brainpalace-status
```

**Example Output:**
```json
{
  "status": "healthy",
  "total_documents": 150,
  "total_chunks": 1200,
  "total_doc_chunks": 800,
  "total_code_chunks": 400
}
```

### `/brainpalace-list`

List all running BrainPalace instances across projects.

```
/brainpalace-list
```

### `/brainpalace-index`

Index documents and/or code.

```
/brainpalace-index ./docs --no-code
/brainpalace-index .
/brainpalace-index ./src --languages python,typescript
/brainpalace-index . --generate-summaries
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--no-code` | code on | Skip source code files (code is indexed by default) |
| `--languages` | all | Languages to index |
| `--generate-summaries` | false | Generate LLM summaries |
| `--chunk-size` | 512 | Chunk size in tokens |

### `/brainpalace-reset`

Clear all indexed documents.

```
/brainpalace-reset
```

---

## Index Management Commands

### `/brainpalace-folders`

Manage indexed folders -- list, add, or remove tracked folders and their chunks.

```
/brainpalace-folders list
/brainpalace-folders add ./docs
/brainpalace-folders add ./src --include-type python,docs
/brainpalace-folders remove ./old-docs --yes
```

**Actions:**

| Action | Description |
|--------|-------------|
| `list` | Show all indexed folders with chunk counts and last indexed timestamps |
| `add` | Queue an indexing job for a folder (supports `--no-code`, `--include-type`, `--force`) |
| `remove` | Remove all indexed chunks for a folder (requires confirmation or `--yes`) |

### `/brainpalace-inject`

Inject custom metadata into chunks during indexing via Python scripts or JSON metadata files. Injectors run after chunking but before embedding.

```
/brainpalace-inject ./docs --script enrich.py
/brainpalace-inject ./src --folder-metadata project-meta.json
/brainpalace-inject ./docs --script enrich.py --dry-run
```

**Options:**

| Option | Description |
|--------|-------------|
| `--script` | Python script exporting `process_chunk(chunk: dict) -> dict` |
| `--folder-metadata` | JSON file with static key-value metadata to merge into all chunks |
| `--dry-run` | Validate injector against sample chunks without indexing |

At least one of `--script` or `--folder-metadata` is required.

### `/brainpalace-types`

List available file type presets for indexing. Presets are named groups of glob patterns for use with the `--include-type` flag.

```
/brainpalace-types
```

Shows presets like `python`, `javascript`, `typescript`, `docs`, `code`, etc. Use with indexing commands:

```
/brainpalace-index ./src --include-type python,docs
/brainpalace-folders add ./repo --include-type code
```

### `/brainpalace-cache`

View embedding cache metrics or clear the cache. The embedding cache avoids redundant API calls during reindexing.

```
/brainpalace-cache status
/brainpalace-cache status --json
/brainpalace-cache clear
/brainpalace-cache clear --yes
```

**Subcommands:**

| Subcommand | Description |
|------------|-------------|
| `status` | Show hit rate, entry counts, and cache size |
| `clear` | Flush all cached embeddings (prompts for confirmation unless `--yes`) |

### `/brainpalace-install-agent`

Install BrainPalace plugin for a specific AI coding runtime. Converts the canonical plugin format into the target runtime's native format.

```
/brainpalace-install-agent --agent claude
/brainpalace-install-agent --agent opencode --project
/brainpalace-install-agent --agent gemini --global
/brainpalace-install-agent --agent claude --dry-run
```

**Supported Runtimes:**

| Runtime | Project Directory | Global Directory |
|---------|-------------------|------------------|
| Claude Code | `.claude/plugins/brainpalace/` | `~/.claude/plugins/brainpalace/` |
| OpenCode | `.opencode/plugins/brainpalace/` | `~/.config/opencode/plugins/brainpalace/` |
| Gemini CLI | `.gemini/plugins/brainpalace/` | `~/.config/gemini/plugins/brainpalace/` |

Use `--dry-run` to preview files that would be created without writing them.

---

## Setup Commands

### `/brainpalace-setup`

Complete guided setup wizard.

```
/brainpalace-setup
```

### `/brainpalace-install`

Install BrainPalace packages.

```
/brainpalace-install
```

Installs:
- `brainpalace-rag` - FastAPI server
- `brainpalace-cli` - Command-line tool

### `/brainpalace-init`

Initialize project directory.

```
/brainpalace-init
```

Creates `.brainpalace/` with project configuration.

### `/brainpalace-config`

View or edit configuration.

```
/brainpalace-config
/brainpalace-config --set default_mode=hybrid
```

### `/brainpalace-verify`

Verify configuration and connectivity.

```
/brainpalace-verify
```

Checks:
- Package installation
- API key configuration
- Server connectivity
- Provider setup

### `/brainpalace-help`

Show help information.

```
/brainpalace-help
/brainpalace-help search
```

### `/brainpalace-version`

Show version information.

```
/brainpalace-version
```

---

## Provider Commands

### `/brainpalace-providers`

List and configure embedding/summarization providers.

```
/brainpalace-providers
```

Interactive wizard for selecting:
- Embedding provider (OpenAI, Ollama, Cohere)
- Summarization provider (Anthropic, OpenAI, Gemini, Grok, Ollama)

### `/brainpalace-embeddings`

Configure embedding provider specifically.

```
/brainpalace-embeddings
/brainpalace-embeddings --provider ollama --model nomic-embed-text
```

### `/brainpalace-summarizer`

Configure summarization provider specifically.

```
/brainpalace-summarizer
/brainpalace-summarizer --provider anthropic --model claude-haiku-4-5-20251001
```

---

## Intelligent Agents

The plugin includes three agents that handle complex, multi-step tasks autonomously.

### Search Assistant

Performs multi-step searches across different modes and synthesizes answers. Can also check embedding cache performance when queries seem slow.

**Triggers:**
- "Find all references to..."
- "Search for..."
- "What files contain..."
- "Where is... defined"
- "Cache performance / slow queries / hit rate"

**Example:**
```
You: "Find all references to the authentication module"

Search Assistant:
1. Searches documentation for auth concepts
2. Searches code for auth imports and usage
3. Uses graph mode to find dependencies
4. Returns comprehensive list with file locations
```

### Research Assistant

Deep exploration with follow-up queries and cross-referencing.

**Triggers:**
- "Research how..."
- "Investigate..."
- "Analyze the architecture of..."
- "Explain the design of..."

**Example:**
```
You: "Research how error handling is implemented across the codebase"

Research Assistant:
1. Identifies error handling patterns in docs
2. Finds exception classes and try/catch blocks
3. Traces error propagation through call graph
4. Synthesizes findings with code references
```

### Setup Assistant

Guided installation, configuration, and troubleshooting. Handles PostgreSQL connection issues, pgvector extension errors, pool exhaustion, and embedding dimension mismatches.

**Triggers:**
- "Help me set up BrainPalace"
- "Configure..."
- "Why isn't... working"
- "Troubleshoot..."
- PostgreSQL connection errors, pgvector missing, pool exhaustion
- Embedding dimension mismatch errors

**Example:**
```
You: "Help me set up BrainPalace with Ollama for local operation"

Setup Assistant:
1. Checks if Ollama is installed
2. Verifies embedding model is pulled
3. Configures provider settings
4. Tests the configuration
5. Reports success or guides through fixes
```

---

## Session Memory (Phases 070 / 080)

Capture finished AI-coding sessions into BrainPalace — **free**, on your
subscription model (no metered API). The AI distils the transcript into a strict
extraction payload (summary + decisions + relationship triplets) and submits it
via `brainpalace submit-session`. See [SESSION_INDEXING.md](SESSION_INDEXING.md).

### `/brainpalace-extract-session`

Runtime-agnostic slash command: the AI reads the current session transcript,
emits the extraction JSON, and submits it.

```
/brainpalace-extract-session
```

### Auto-extraction agents + hooks (Claude Code)

| Asset | Role |
|---|---|
| `agents/chat-session-extractor.md` | Subagent that extracts + submits a finished session (read-only tools + submit). |
| `agents/memory-curator.md` | Distils recent decisions into curated memory; prunes/merges. |
| `templates/sessionend-hook.sh` | Queues the ended `session_id` for extraction. |
| `templates/sessionstart-hook.sh` | Drains the queue → runs the extractor subagent (free, in-session model). |
| `templates/daily-distill-hook.sh` / `weekly-curate-hook.sh` | Opt-in periodic curation. |

Auto-extraction is **best-effort** (runs at the next session start); the manual
command is always available. All opt-in; only indexed projects with session
indexing enabled extract.

---

## Skills

The plugin includes two skills that provide context-aware assistance.

### using-brainpalace

Provides Claude with knowledge about:
- Optimal search mode selection (BM25, vector, hybrid, graph, multi)
- Query optimization techniques
- Folder management and file type presets for indexing
- Content injection with custom scripts and metadata
- Embedding cache monitoring and management
- File watcher behavior and incremental indexing
- Job queue monitoring
- Result interpretation and API usage patterns

**When Active:** Claude automatically selects the best search mode for your query type and can manage folders, cache, and indexing jobs.

### configuring-brainpalace

Provides Claude with knowledge about:
- Installation procedures for packages and plugins
- Multi-runtime installation (Claude Code, OpenCode, Gemini CLI) via `install-agent`
- Provider configuration (7 providers: OpenAI, Anthropic, Ollama, Cohere, Gemini, Grok, SentenceTransformers)
- Embedding cache configuration and tuning
- GraphRAG setup and graph store selection
- Setup wizard configuration flow
- Troubleshooting steps and environment setup

**When Active:** Claude can guide you through setup, configure providers, install for multiple runtimes, and resolve configuration issues.

---

## Search Modes

| Mode | Command | Best For | Speed |
|------|---------|----------|-------|
| HYBRID | `/brainpalace-search` | General questions | Medium |
| VECTOR | `/brainpalace-semantic` | Conceptual queries | Slow |
| BM25 | `/brainpalace-keyword` | Exact terms, function names | Fast |
| GRAPH | `/brainpalace-graph` | Dependencies, relationships | Medium |
| MULTI | `/brainpalace-multi` | Maximum recall | Slowest |

### Mode Selection Guide

| Query Type | Recommended Mode | Example |
|------------|------------------|---------|
| "How does X work?" | HYBRID or VECTOR | "how does caching work" |
| Function/class name | BM25 | "getUserById" |
| Error message | BM25 | "NullPointerException" |
| "What calls X?" | GRAPH | "what calls AuthService" |
| "Everything about X" | MULTI | "everything about validation" |
| Conceptual question | VECTOR | "explain the architecture" |

---

## Provider Configuration

### Embedding Providers

| Provider | Models | Local | API Key |
|----------|--------|-------|---------|
| OpenAI | text-embedding-3-large, text-embedding-3-small | No | OPENAI_API_KEY |
| Ollama | nomic-embed-text, mxbai-embed-large | Yes | None |
| Cohere | embed-english-v3.0, embed-multilingual-v3.0 | No | COHERE_API_KEY |

### Summarization Providers

| Provider | Models | Local | API Key |
|----------|--------|-------|---------|
| Anthropic | claude-haiku-4-5-20251001, claude-sonnet-4-5-20250514 | No | ANTHROPIC_API_KEY |
| OpenAI | gpt-5, gpt-5-mini | No | OPENAI_API_KEY |
| Gemini | gemini-3-flash, gemini-3-pro | No | GOOGLE_API_KEY |
| Grok | grok-4, grok-4-fast | No | GROK_API_KEY |
| Ollama | llama4:scout, mistral-small3.2, qwen3-coder | Yes | None |

### Fully Local Mode

Run completely offline with Ollama:

```
/brainpalace-providers
# Select Ollama for embeddings
# Select Ollama for summarization
```

Required Ollama models:
```bash
ollama pull nomic-embed-text
ollama pull llama4:scout
```

---

## Integration Patterns

### CI/CD Integration

```yaml
# .github/workflows/docs-check.yml
jobs:
  validate-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install BrainPalace
        run: |
          pip install --upgrade \
            "git+https://github.com/bxw91/brainpalace.git@stable#subdirectory=brainpalace-cli" \
            "git+https://github.com/bxw91/brainpalace.git@stable#subdirectory=brainpalace-server"
      - name: Start and Index
        run: |
          brainpalace init
          brainpalace start --daemon
          brainpalace index ./docs
      - name: Validate
        run: brainpalace status
```

### Python API

```python
import httpx
import json
from pathlib import Path

# Discover server
runtime = json.loads(Path(".brainpalace/runtime.json").read_text())
base_url = runtime["base_url"]

# Query
async with httpx.AsyncClient() as client:
    response = await client.post(
        f"{base_url}/query",
        json={"query": "authentication", "mode": "hybrid", "top_k": 5}
    )
    for result in response.json()["results"]:
        print(f"{result['source']}: {result['score']:.2f}")
```

---

## Troubleshooting

### Server Not Running

```
/brainpalace-status
# If not running:
/brainpalace-start
```

### No Results Found

1. Check document count: `/brainpalace-status`
2. If 0 documents: `/brainpalace-index ./docs`
3. Lower threshold: `/brainpalace-search "term" --threshold 0.3`
4. Try keyword search: `/brainpalace-keyword "exact term"`

### GraphRAG Not Working

GraphRAG requires explicit enablement:

```
/brainpalace-config --set enable_graph_index=true
/brainpalace-stop
/brainpalace-start
/brainpalace-index .
```

### Provider Errors

```
/brainpalace-verify
/brainpalace-providers
```

Verify API keys are set correctly for your selected provider.

### Reset Everything

```
/brainpalace-reset
/brainpalace-init
/brainpalace-start
/brainpalace-index .
```

---

## Reference Documentation

| Guide | Description |
|-------|-------------|
| [API Reference](API_REFERENCE.md) | REST API documentation |
| [GraphRAG Guide](GRAPHRAG_GUIDE.md) | Knowledge graph features |
| [Code Indexing](CODE_INDEXING.md) | AST-aware chunking |
| [Architecture](ARCHITECTURE.md) | System design |
| [Provider Configuration](../brainpalace-plugin/skills/using-brainpalace/references/provider-configuration.md) | Provider setup |
| [PostgreSQL Setup](POSTGRESQL_SETUP.md) | Docker Compose pgvector setup |
| [Performance Tradeoffs](PERFORMANCE_TRADEOFFS.md) | ChromaDB vs PostgreSQL selection guidance |

---

## Next Steps

- [Quick Start](QUICK_START.md) - Get running in minutes
- [User Guide](USER_GUIDE.md) - Detailed usage patterns
- [Developer Guide](DEVELOPERS_GUIDE.md) - Contributing to BrainPalace
