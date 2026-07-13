---
last_validated: 2026-07-13
---

# BrainPalace Plugin Guide

Complete reference for the BrainPalace Claude Code plugin - 42 commands, 6 agents, and 2 skills for intelligent document and code search.

## Table of Contents

- [Installation](#installation)
- [Quick Setup](#quick-setup)
- [Search Command](#search-command)
- [Server Commands](#server-commands)
- [Index Management Commands](#index-management-commands)
- [Setup & Config Commands](#setup--config-commands)
- [Memory & Session Commands](#memory--session-commands)
- [Diagnostics & Lifecycle Commands](#diagnostics--lifecycle-commands)
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
- **42 slash commands** for all operations
- **6 intelligent agents** for complex tasks
- **2 skills** for context-aware assistance

### SessionStart hook

The plugin ships a SessionStart hook
(`brainpalace-plugin/hooks/sessionstart-hook.sh`) that emits a context
reminder (and, when enabled, an injected project-context block) when Claude
Code opens a directory that has a `.brainpalace/` index.

### Updating the plugin

Update later from inside Claude Code (then restart the session):

```bash
claude plugin update brainpalace@brainpalace-marketplace
```

---

## Quick Setup

The fastest way to get started:

```
/brainpalace-setup
```

This interactive wizard:
1. Installs packages (`brainpalace-rag`, `brainpalace-cli`)
2. Configures API keys
3. Initializes your project — **configure-only** (`init --defer-activation`):
   it does not start the server or index, and won't auto-start

Then **you** start it the first time yourself (it won't auto-start until you
do): `brainpalace start` (or the dashboard Instances → Start), which also kicks
off the first index. After that first manual start, the project autostarts
normally on future sessions.

Or step-by-step:

```
/brainpalace-install     # Install packages
/brainpalace-config      # Configure providers + API keys (wizard)
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

## Search Command

All retrieval goes through a single command, `/brainpalace-query`, with a
`--mode` flag selecting the strategy. (Earlier releases shipped a separate slash
command per mode — those have been consolidated.)

### `/brainpalace-query`

Search indexed documents with a natural-language or keyword query.

```
/brainpalace-query "how does authentication work"
/brainpalace-query "NullPointerException" --mode bm25
/brainpalace-query "explain the overall architecture" --mode vector
/brainpalace-query "what calls AuthService" --mode graph
/brainpalace-query "complete authentication flow" --mode multi --top-k 10
```

**Modes (`--mode`, default `hybrid`):**

| Mode | Best for |
|------|----------|
| `hybrid` | General questions (vector + BM25, the default) |
| `vector` | Conceptual / semantic queries |
| `bm25` | Exact terms, function names, error codes |
| `graph` | Dependencies and relationships (needs `ENABLE_GRAPH_INDEX=true`) |
| `multi` | Maximum recall (fusion of vector + bm25 + graph) |

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--mode`, `-m` | `hybrid` | Retrieval mode (see table above) |
| `--top-k`, `-k` | 5 | Number of results |
| `--threshold`, `-t` | 0.3 | Minimum similarity (0.0-1.0) |
| `--alpha`, `-a` | 0.5 | Hybrid weight: `1.0` = pure vector, `0.0` = pure bm25 |
| `--source-types` | all | Filter: `doc`, `code`, `test` (comma-separated) |
| `--languages` | all | Filter by programming language |
| `--file-paths` | all | Filter by path patterns (wildcards supported) |
| `--scores` | false | Show individual vector/BM25 scores |
| `--full` | false | Show full text content |
| `--json` | false | Output as JSON |
| `--no-time-decay` | false | Disable age-weighted ranking for this query |
| `--language` | "" | BM25 query language override (ISO 639-1, e.g. `en`, `de`, `hr`) |

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

### `/brainpalace-whoami`

Show which BrainPalace project and server own the current directory.

```
/brainpalace-whoami
```

### `/brainpalace-index`

Index documents and/or code.

```
/brainpalace-index ./docs --no-code
/brainpalace-index .
/brainpalace-index ./src --languages python,typescript
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--no-code` | code on | Skip source code files (code is indexed by default) |
| `--languages` | all | Languages to index |
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

### `/brainpalace-jobs`

Monitor and manage async indexing jobs in the queue. Large indexing runs are
dispatched to a background job worker.

```
/brainpalace-jobs
```

### `/brainpalace-install-agent`

Install BrainPalace plugin for a specific AI coding runtime. Converts the canonical plugin format into the target runtime's native format.

```
/brainpalace-install-agent --agent claude
/brainpalace-install-agent --agent opencode --project
/brainpalace-install-agent --agent gemini --global
/brainpalace-install-agent --agent claude --dry-run
```

**Supported Runtimes:**

<!--GENERATED:install-dirs-->
| Runtime | Project dir | Global dir |
|---------|-------------|------------|
| `claude` | `.claude/plugins/brainpalace` | `~/.claude/plugins/brainpalace` |
| `opencode` | `.opencode/plugins/brainpalace` | `~/.config/opencode/plugins/brainpalace` |
| `gemini` | `.gemini/plugins/brainpalace` | `~/.config/gemini/plugins/brainpalace` |
| `codex` | `.codex/skills/brainpalace` | `~/.codex/skills/brainpalace` |
<!--/GENERATED-->

Use `--dry-run` to preview files that would be created without writing them.

---

## Setup & Config Commands

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

The 12-step configuration wizard — providers (embedding + summarization),
storage backend, GraphRAG, reranking, caching, file watcher, chunking, and
server deployment. This is also where embedding/summarization **providers and
API keys** are configured (there is no separate `providers`/`embeddings`/`summarizer`
command).

```
/brainpalace-config
```

The underlying `brainpalace config` CLI group exposes `show`, `path`, `wizard`,
`validate`, `migrate`, `diff`, and `unset <dotpath>` subcommands. (There is no
`--set` flag — edit config via the wizard or `config unset` to drop a project
override so a key re-inherits from global.)

### `/brainpalace-doctor`

Diagnose your setup — Python, config, API keys, and server reachability.

```
/brainpalace-doctor
```

### `/brainpalace-verify`

Verify installation and configuration.

```
/brainpalace-verify
```

Checks package installation, API key configuration, server connectivity, and
provider setup.

### `/brainpalace-install-agent`

Install the plugin into another AI coding runtime (see the runtime table under
[Index Management Commands](#index-management-commands)).

### `/brainpalace-install-session-hooks`

Install BrainPalace's Claude Code SessionStart reminder hook.

```
/brainpalace-install-session-hooks
```

> Help and version are not plugin commands — use Claude Code's own `/help` and
> the CLI's `brainpalace --version`.

---

## Intelligent Agents

The plugin includes six agents that handle complex, multi-step tasks
autonomously. Three are interactive (below); the other three —
**Chat Session Extractor**, **Memory Curator**, and **Graph Triplet Extractor** —
drive session capture, curated memory, and knowledge-graph extraction and are
documented under [Session Memory](#session-memory-phases-070--080).

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
| `hooks/sessionstart-hook.sh` | Drains the queue → runs the extractor subagent (free, in-session model). |
| `templates/daily-distill-hook.sh` / `weekly-curate-hook.sh` | Opt-in periodic curation. |

Auto-extraction is **best-effort** (runs at the next session start); the manual
command is always available. All opt-in; only indexed projects with session
indexing enabled extract.

---

## Memory & Session Commands

The curated-memory namespace (`BRAINPALACE_MEMORY.md`) is separate from the
document index — durable facts and decisions you choose to keep.

### `/brainpalace-remember`

Save a curated fact to the project's memory.

```
/brainpalace-remember "We use ChromaDB by default; Postgres is opt-in"
```

### `/brainpalace-recall`

Recall curated memories matching a query (memory namespace only).

```
/brainpalace-recall "storage backend"
```

### `/brainpalace-memories`

Manage the curated memory namespace — list, show, delete, obsolete.

```
/brainpalace-memories list
```

### `/brainpalace-context`

Print the session-start context block (project facts + curated memory).

```
/brainpalace-context
```

---

## Diagnostics & Lifecycle Commands

### `/brainpalace-ai-guide`

Print the canonical AI usage guidance (search modes, query rules, gotchas).

```
/brainpalace-ai-guide
```

### `/brainpalace-dashboard`

Launch, stop, or inspect the BrainPalace web control-plane dashboard.

```
/brainpalace-dashboard
```

### `/brainpalace-mcp`

Serve BrainPalace over stdio for MCP-aware AI clients.

```
/brainpalace-mcp
```

### `/brainpalace-plugin`

Inspect the BrainPalace Claude Code plugin (installation status).

```
/brainpalace-plugin
```

### `/brainpalace-read-only`

Enable/disable read-only mode (disables embedding, summarization, and writes).

```
/brainpalace-read-only
```

### `/brainpalace-update`

Upgrade BrainPalace (CLI + server + dashboard) to the latest version.

```
/brainpalace-update
```

### `/brainpalace-uninstall`

Uninstall BrainPalace (guided teardown, or global-only with `--yes`/`--json`).

```
/brainpalace-uninstall
```

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
| HYBRID | `/brainpalace-query` (default) | General questions | Medium |
| VECTOR | `/brainpalace-query --mode vector` | Conceptual queries | Slow |
| BM25 | `/brainpalace-query --mode bm25` | Exact terms, function names | Fast |
| GRAPH | `/brainpalace-query --mode graph` | Dependencies, relationships | Medium |
| MULTI | `/brainpalace-query --mode multi` | Maximum recall | Slowest |

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

<!--GENERATED:providers-embedding-->
| Provider | API key env var | Models (default first) |
|----------|-----------------|------------------------|
| `openai` | `OPENAI_API_KEY` | `text-embedding-3-large`, `text-embedding-3-small` |
| `cohere` | `COHERE_API_KEY` | `embed-english-v3.0`, `embed-multilingual-v3.0` |
| `ollama` | _(none — local)_ | `nomic-embed-text`, `mxbai-embed-large` |
<!--/GENERATED-->

### Summarization Providers

<!--GENERATED:providers-summarization-->
| Provider | API key env var | Models (default first) |
|----------|-----------------|------------------------|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-4-5-20251001`, `claude-sonnet-4-5-20250514` |
| `openai` | `OPENAI_API_KEY` | `gpt-5-mini`, `gpt-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.1-flash-lite`, `gemini-3.5-flash` |
| `grok` | `XAI_API_KEY` | `grok-4`, `grok-4-fast` |
| `ollama` | _(none — local)_ | `llama4:scout`, `mistral-small3.2`, `qwen3-coder` |
<!--/GENERATED-->

### Fully Local Mode

Run completely offline with Ollama:

```
/brainpalace-config
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
            "git+https://github.com/bxw91/brainpalace.git@main#subdirectory=brainpalace-cli" \
            "git+https://github.com/bxw91/brainpalace.git@main#subdirectory=brainpalace-server"
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
3. Lower threshold: `/brainpalace-query "term" --threshold 0.1`
4. Try keyword search: `/brainpalace-query "exact term" --mode bm25`

### GraphRAG Not Working

GraphRAG requires explicit enablement. Enable it via the config wizard (GraphRAG
step) or set `ENABLE_GRAPH_INDEX=true`, then restart and re-index:

```
/brainpalace-config
# enable GraphRAG at the GraphRAG step
/brainpalace-stop
/brainpalace-start
/brainpalace-index .
```

### Provider Errors

```
/brainpalace-verify
/brainpalace-config
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
