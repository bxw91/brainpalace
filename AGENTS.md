---
last_validated: 2026-07-23
---

# AGENTS.md

> **Repo dev guide lives in [CLAUDE.md](CLAUDE.md) — read it first.**
> It is the single, authoritative guide for working on this repository
> (monorepo layout, build/test gate cadence, setup/dashboard/AI-guidance
> parity rules, releasing). It applies to every coding agent, not just
> Claude. This file adds only the BrainPalace plugin usage block below;
> it deliberately does not duplicate CLAUDE.md.

<!-- brainpalace:start -->

## BrainPalace

BrainPalace provides semantic search over your codebase and documentation.

### Available Skills

| Skill | Description |
|-------|-------------|
| brainpalace-ai-guide | Print canonical AI usage guidance (search modes, query rules, gotchas) |
| brainpalace-cache | View embedding cache metrics or clear the cache |
| brainpalace-config | Configure all BrainPalace settings interactively via the unified registry-driven editor — providers, storage, GraphRAG, reranking, sessions, git-history, and more |
| brainpalace-context | Print the session-start context block (project facts + curated memory) |
| brainpalace-dashboard | Launch, stop, or inspect the BrainPalace web control-plane dashboard |
| brainpalace-doctor | Diagnose your BrainPalace setup (Python, config, keys, server reachability) |
| brainpalace-entities | Manage identity — person / alias / link, plus deterministic candidate resolution (who someone is) |
| brainpalace-extract-session | Manually extract the current AI-coding session into BrainPalace memory (summary, decisions, knowledge-graph triplets) |
| brainpalace-extraction | Graph-extraction drain queue (used by the AI drain command) |
| brainpalace-folders | Manage indexed folders — list, add, or remove |
| brainpalace-graph | Structural graph queries — shortest paths, impact analysis, and co-change |
| brainpalace-index | Index documents for semantic search |
| brainpalace-ingest | Ingest content into BrainPalace with caller-supplied provenance |
| brainpalace-init | Initialize BrainPalace for the current project |
| brainpalace-inject | Inject custom metadata into chunks during indexing via Python scripts or JSON metadata files |
| brainpalace-install-agent | Install BrainPalace plugin for a specific runtime (Claude, OpenCode, Codex, Antigravity, Qwen Code, Kimi CLI, skill-runtime) |
| brainpalace-install-mcp | Write BrainPalace's MCP server into the project's .mcp.json |
| brainpalace-install-session-hooks | Install BrainPalace's Claude Code SessionStart reminder hook |
| brainpalace-install | Install BrainPalace packages using pipx, uv, pip, or conda |
| brainpalace-jobs | Monitor and manage async indexing jobs in the queue |
| brainpalace-list | List all running BrainPalace instances across projects |
| brainpalace-lsp | Manage LSP language servers used for exact cross-file graph edges |
| brainpalace-mcp | Serve BrainPalace over stdio for MCP-aware AI clients |
| brainpalace-memories | Manage the curated memory namespace (list, show, delete, obsolete) |
| brainpalace-plugin | Inspect the BrainPalace Claude Code plugin (installation status) |
| brainpalace-query | Search indexed documents with a natural language or keyword query |
| brainpalace-read-only | Enable/disable read-only mode (disables embedding, summarization, writes) |
| brainpalace-recall | Recall curated memories matching a query (memory namespace only) |
| brainpalace-records | Manage typed numeric records (compute mode) — stats, revalidation, salience recompute |
| brainpalace-references | Search and manage the lazy-tier reference catalog — list, semantic search, resolve, and backfill embeddings |
| brainpalace-rehome | Show or resume the project-move rehome quarantine |
| brainpalace-remember | Save a curated fact to the project's memory (BRAINPALACE_MEMORY.md) |
| brainpalace-reset | Clear the document index (requires confirmation) |
| brainpalace-rules | Manage durable taught confidence rules (compute-mode trust) |
| brainpalace-setup | Complete guided setup for BrainPalace (install, config, init, verify) |
| brainpalace-start | Start the BrainPalace server for this project |
| brainpalace-status | Show BrainPalace server status (health, documents, cache, watcher) |
| brainpalace-stop | Stop the BrainPalace server for this project |
| brainpalace-types | List available file type presets for indexing |
| brainpalace-uninstall | Uninstall BrainPalace (guided teardown, or global-only with --yes/--json) |
| brainpalace-update | Upgrade BrainPalace (CLI + server + dashboard) to the latest version |
| brainpalace-verify | Verify BrainPalace installation and configuration |
| brainpalace-whoami | Show which BrainPalace project and server own the current directory |
| chat-session-extractor | Extract durable knowledge (summary, decisions, relationship triplets) from a finished AI-coding session and submit it to BrainPalace |
| graph-triplet-extractor | Extract entity/relationship triplets from a single indexed document chunk and submit them to BrainPalace's graph (free, Haiku — the subagent executor of the shared extraction queue) |
| memory-curator | Distil recent session decisions into curated memory and prune/merge stale or duplicate memories ("daily distill" / "weekly curate"), on the subscription model |
| research-assistant | Intelligent research agent that uses BrainPalace for knowledge retrieval with adaptive search modes |
| search-assistant | Proactively assists with document and code search using BrainPalace — use for "search the docs", "find documentation about", "where is X", "find the implementation of", "query the knowledge base", and cache/hit-rate questions |
| setup-assistant | Proactively assists with BrainPalace installation and configuration — use for install/setup/config requests, "command not found", missing API keys, Postgres/pgvector connection errors, embedding dimension mismatches, and BM25 language questions |
| configuring-brainpalace | Installation and configuration skill for BrainPalace document search system.
Use when asked to "install BrainPalace", "setup BrainPalace", "configure BrainPalace",
"setting up document search", "installing brainpalace packages", "configuring API keys",
"initializing project for search", "troubleshooting BrainPalace", "pip install brainpalace",
"BrainPalace not working", "BrainPalace setup error", "configure embeddings provider",
"setup ollama for BrainPalace", or "BrainPalace environment variables".
Covers package installation, provider configuration, project initialization, and server management.
 |
| using-brainpalace | Expert BrainPalace skill for document search with BM25 keyword, semantic
vector, hybrid, graph, multi, compute, scan, absence, and timeline
retrieval modes.
Use when asked to "search documentation", "query domain", "find in docs",
"bm25 search", "hybrid search", "semantic search", "graph search", "multi search",
"compute query", "scan sessions", "absence query", "timeline query",
"find dependencies", "code relationships", "searching knowledge base",
"querying indexed documents", "finding code references", "exploring codebase",
"what calls this function", "find imports", "trace dependencies",
"brain search", "brain query", "knowledge base search",
"cache management", "clear embedding cache", "cache hit rate", or "cache status".
Supports multi-instance architecture with automatic server discovery.
GraphRAG mode enables relationship-aware queries for code dependencies and
entity connections.
Pluggable providers for embeddings (OpenAI, Cohere, Ollama) and summarization
(Anthropic, OpenAI, Gemini, Grok, Ollama).
Supports multiple runtimes (Claude Code, OpenCode, Gemini CLI) with shared
.brainpalace/ data directory.
 |

### Usage

Ask your AI assistant to search documentation or code:

- "Search for authentication patterns in my codebase"
- "Find documentation about the API endpoints"
- "Look up how error handling works"

### Setup

Run `brainpalace start` to start the BrainPalace server, then use
`brainpalace index ./src` to index your source code.

<!-- brainpalace:end -->
