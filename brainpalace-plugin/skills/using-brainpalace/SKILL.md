---
name: using-brainpalace
description: |
  Expert BrainPalace skill for document search with BM25 keyword, semantic vector, hybrid, graph, and multi retrieval modes.
  Use when asked to "search documentation", "query domain", "find in docs",
  "bm25 search", "hybrid search", "semantic search", "graph search", "multi search",
  "find dependencies", "code relationships", "searching knowledge base",
  "querying indexed documents", "finding code references", "exploring codebase",
  "what calls this function", "find imports", "trace dependencies",
  "brain search", "brain query", "knowledge base search",
  "cache management", "clear embedding cache", "cache hit rate", or "cache status".
  Supports multi-instance architecture with automatic server discovery.
  GraphRAG mode enables relationship-aware queries for code dependencies and entity connections.
  Pluggable providers for embeddings (OpenAI, Cohere, Ollama) and summarization (Anthropic, OpenAI, Gemini, Grok, Ollama).
  Supports multiple runtimes (Claude Code, OpenCode, Gemini CLI) with shared .brainpalace/ data directory.
license: MIT
allowed-tools:
  - Bash
  - Read
metadata:
  version: 7.0.0
  category: ai-tools
  author: bxw91
  last_validated: 2026-06-05
---

# BrainPalace Expert Skill

Expert-level skill for BrainPalace document search with five modes: BM25 (keyword), Vector (semantic), Hybrid (fusion), Graph (knowledge graph), and Multi (comprehensive fusion).

## Mode Decision Table — Quick Reference

Use this table to pick `--mode` for any inline search. Default to `hybrid` when unsure.

| Query type | Mode |
|---|---|
| General / unknown | `--mode hybrid` |
| Conceptual ("how does X work") | `--mode vector` |
| Exact symbol / error / token / file path | `--mode bm25` |
| Relationships ("what calls X", "what imports Y") | `--mode graph` |
| Maximum recall (ALL usages / references) | `--mode multi` |

### Before Anything Else — Project Indexed Check

Run this check **first**, before applying any rule below:

```bash
brainpalace whoami    # exits 0 (indexed + server up), 1 (no project), or 2 (indexed but server down)
```

Branch on exit code:

- **Exit `0`** → project has `.brainpalace/` AND server is running. Skill applies. Continue reading below.
- **Exit `1`** → no `.brainpalace/` in CWD or any ancestor. **Skill yields silently.**
  Use native Glob / Grep / Read tools for codebase search as normal.
  Optionally suggest the user run `brainpalace init` if they want indexed search.
  Do NOT print enforcement warnings. Do NOT block the task.
- **Exit `2`** → project IS indexed but server not running. Skill applies but searches will fail until server starts. Follow the "When BrainPalace Server Is Down" branch below.

If the `brainpalace` CLI is not installed at all (command not found), treat as exit `1` and yield.

### Search Rule — Non-Negotiable (when project is indexed)

When the indexed-check above passed: BrainPalace is the first entry point for codebase search. Never use Glob, Grep, or Bash `find`/`rg` against indexed project source — even when you think you know the path or token. Use the table above to pick a mode, then:

```bash
brainpalace query "..." --mode <picked-from-table> --top-k 8 --json
```

After BrainPalace returns confirmed file paths, use `Read` to read those files directly.

**Allowed Glob/Grep cases (NOT codebase search):**
- Searching INSIDE a single file BrainPalace already returned
- Non-indexed paths: `~/.claude/`, `~/.config/`, `/tmp/`, dotfiles, settings/log files
- Files modified since the project's `last_indexed` timestamp (`brainpalace folders list`)
- Paths excluded by project's `.brainpalace/config.json` `exclude_patterns`
- Listing directory STRUCTURE only: `ls`, `find <path> -maxdepth N -type d`

### When BrainPalace Server Is Down

If `brainpalace query` returns connection-refused / `/health/` non-200 (project IS indexed but server not running):
1. Task needs codebase search → STOP. Tell user "BrainPalace server not running. Start it with `brainpalace start`."
2. Task does NOT need codebase search → proceed normally.
3. NEVER fall back to Glob/Grep/find for codebase search "just this once".

Note: server-down is distinct from project-not-indexed. The former means `.brainpalace/` exists but the server process is not running; the latter means no `.brainpalace/` exists at all and the skill should yield.

---

## Contents

- [Search Modes](#search-modes)
- [Mode Selection Guide](#mode-selection-guide)
- [BM25 Language Override](#bm25-language-override)
- [GraphRAG (Knowledge Graph)](#graphrag-knowledge-graph)
- [Indexing & Folder Management](#indexing--folder-management)
- [Content Injection](#content-injection)
- [Job Queue Management](#job-queue-management)
- [Server Management](#server-management)
- [Cache Management](#cache-management)
- [When Not to Use](#when-not-to-use)
- [Best Practices](#best-practices)
- [Reference Documentation](#reference-documentation)

---

## Search Modes

| Mode | Speed | Best For | Example Query |
|------|-------|----------|---------------|
| `bm25` | Fast (10-50ms) | Technical terms, function names, error codes | `"AuthenticationError"` |
| `vector` | Slower (800-1500ms) | Concepts, explanations, natural language | `"how authentication works"` |
| `hybrid` | Slower (1000-1800ms) | Comprehensive results combining both | `"OAuth implementation guide"` |
| `graph` | Medium (500-1200ms) | Relationships, dependencies, call chains | `"what calls AuthService"` |
| `multi` | Slowest (1500-2500ms) | Most comprehensive with entity context | `"complete auth flow with dependencies"` |

### Mode Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--mode` | hybrid | Search mode: bm25, vector, hybrid, graph, multi |
| `--threshold` | 0.3 | Minimum similarity (0.0-1.0) |
| `--top-k` | 5 | Number of results |
| `--alpha` | 0.5 | Hybrid balance (0=BM25, 1=Vector) |
| `--language` | project `bm25.language` (default `en`) | Per-query BM25 tokenization language override (ISO 639-1). Applies to `bm25` and `hybrid` modes; ignored for `vector`, `graph`, `multi`. |

---

## Mode Selection Guide

### Use BM25 When

Searching for exact technical terms:

```bash
brainpalace query "recursiveCharacterTextSplitter" --mode bm25
brainpalace query "ValueError: invalid token" --mode bm25
brainpalace query "def process_payment" --mode bm25
```

**Counter-example - Wrong mode choice**:
```bash
# BM25 is wrong for conceptual queries
brainpalace query "how does error handling work" --mode bm25  # Wrong
brainpalace query "how does error handling work" --mode vector  # Correct
```

#### BM25 Language Override

BM25 and hybrid modes apply language-aware stemming. By default the project language (`bm25.language`, default `en`) is used. Override per-query with `--language`:

```bash
# Query a German-language document set
brainpalace query "Authentifizierungsablauf" --mode bm25 --language de

# Hybrid search with French tokenization override
brainpalace query "gestion des erreurs" --mode hybrid --language fr

# Croatian (lemma engine must be configured at project level)
brainpalace query "upravljanje pogreškama" --mode bm25 --language hr
```

The `--language` flag maps to `QueryRequest.language` and only affects BM25 tokenization for that single query. `vector`, `graph`, and `multi` modes are not affected by `--language`.

### Use Vector When

Searching for concepts or natural language:

```bash
brainpalace query "best practices for error handling" --mode vector
brainpalace query "how to implement caching" --mode vector
```

**Counter-example - Wrong mode choice**:
```bash
# Vector is wrong for exact function names
brainpalace query "getUserById" --mode vector  # Wrong - may miss exact match
brainpalace query "getUserById" --mode bm25    # Correct - finds exact match
```

### Use Hybrid When

Need comprehensive results (default mode):

```bash
brainpalace query "OAuth implementation" --mode hybrid --alpha 0.6
brainpalace query "database connection pooling" --mode hybrid
```

**Alpha tuning**:
- `--alpha 0.3` - More keyword weight (technical docs)
- `--alpha 0.7` - More semantic weight (conceptual docs)

### Use Graph When

Exploring relationships and dependencies:

```bash
brainpalace query "what functions call process_payment" --mode graph
brainpalace query "classes that inherit from BaseService" --mode graph --traversal-depth 3
brainpalace query "modules that import authentication" --mode graph
```

**Prerequisite**: Requires `ENABLE_GRAPH_INDEX=true` during server startup.

### Use Multi When

Need the most comprehensive results:

```bash
brainpalace query "complete payment flow implementation" --mode multi --include-relationships
```

---

## GraphRAG (Knowledge Graph)

GraphRAG enables relationship-aware retrieval by building a knowledge graph from indexed documents.

### Enabling GraphRAG

```bash
export ENABLE_GRAPH_INDEX=true
brainpalace start
```

### Graph Query Types

| Query Pattern | Example |
|---------------|---------|
| Function callers | `"what calls process_payment"` |
| Class inheritance | `"classes extending BaseController"` |
| Import dependencies | `"modules importing auth"` |
| Data flow | `"where does user_id come from"` |

See [Graph Search Guide](references/graph-search-guide.md) for detailed usage.

---

## Indexing & Folder Management

### Indexing with File Type Presets

```bash
# Index only Python files
brainpalace index ./src --include-type python

# Index Python and documentation
brainpalace index ./project --include-type python,docs

# Index all code files
brainpalace index ./repo --include-type code

# Force full re-index (bypass incremental)
brainpalace index ./docs --force
```

Use `brainpalace types list` to see all 14 available presets.

### Folder Management

```bash
brainpalace folders list                    # List indexed folders with chunk counts
brainpalace folders add ./docs              # Add folder (triggers indexing)
brainpalace folders add ./src --include-type python  # Add with preset filter
brainpalace folders remove ./old-docs --yes # Remove folder and evict chunks
```

### Incremental Indexing

Re-indexing a folder automatically detects changes:
- **Unchanged files** are skipped (mtime + SHA-256 checksum)
- **Changed files** have old chunks evicted and new ones created
- **Deleted files** have their chunks automatically removed
- Use `--force` to bypass manifest and fully re-index

---

## Content Injection

Enrich chunk metadata during indexing with custom Python scripts or static JSON metadata.

### When to Use

- Tag chunks with project/team/category metadata
- Classify chunks by content type
- Add custom fields for filtered search
- Merge folder-level metadata into all chunks

### Basic Usage

```bash
# Inject via Python script
brainpalace inject ./docs --script enrich.py

# Inject via static JSON metadata
brainpalace inject ./src --folder-metadata project-meta.json

# Validate script before indexing
brainpalace inject ./docs --script enrich.py --dry-run
```

### Injector Script Protocol

Scripts export a `process_chunk(chunk: dict) -> dict` function:

```python
def process_chunk(chunk: dict) -> dict:
    chunk["project"] = "my-project"
    chunk["team"] = "backend"
    return chunk
```

- Values must be scalars (str, int, float, bool)
- Per-chunk exceptions are logged as warnings, not fatal
- See `docs/INJECTOR_PROTOCOL.md` for the full specification

---

## Job Queue Management

Indexing runs asynchronously via a job queue. Monitor and manage jobs:

```bash
brainpalace jobs                    # List all jobs
brainpalace jobs --watch            # Live polling every 3s
brainpalace jobs <job_id>           # Job details + eviction summary
brainpalace jobs <job_id> --cancel  # Cancel a job
```

### Eviction Summary

When re-indexing, job details show what changed:

```
Eviction Summary:
  Files added:     3
  Files changed:   2
  Files deleted:   1
  Files unchanged: 42
  Chunks evicted:  15
  Chunks created:  25
```

This confirms incremental indexing is working efficiently.

---

## Server Management

### Quick Start

```bash
brainpalace init              # Initialize project (first time)
brainpalace start    # Start server
brainpalace index ./docs      # Index documents
brainpalace query "search"    # Search
brainpalace stop              # Stop when done
```

**Progress Checklist:**
- [ ] `/brainpalace:brainpalace-init` succeeded
- [ ] `/brainpalace:brainpalace-status` shows healthy
- [ ] Document count > 0
- [ ] Query returns results (or "no matches" - not error)

### Lifecycle Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-init` | Initialize project config |
| `/brainpalace:brainpalace-start` | Start with auto-port |
| `/brainpalace:brainpalace-status` | Show port, mode, document count |
| `/brainpalace:brainpalace-list` | List all running instances |
| `/brainpalace:brainpalace-stop` | Graceful shutdown |

### Pre-Query Validation

Before querying, verify setup:

```bash
brainpalace status
```

Expected:
- Status: healthy
- Documents: > 0
- Provider: configured

**Counter-example - Querying without validation**:
```bash
# Wrong - querying without checking status
brainpalace query "search term"  # May fail if server not running

# Correct - validate first
brainpalace status && brainpalace query "search term"
```

See [Server Discovery Guide](references/server-discovery.md) for multi-instance details.

---

## Cache Management

The embedding cache automatically stores computed embeddings to avoid redundant API calls
during reindexing. No setup is required — the cache is active by default.

### When to Check Cache Status

- **After indexing** — verify cache is working and hit rate is growing
- **When queries seem slow** — a low or zero hit rate means embeddings are being recomputed on every reindex
- **To monitor cache growth** — track disk usage over time for large indexes

```bash
brainpalace cache status
```

A healthy cache shows:
- Hit rate > 80% after the first full reindex cycle
- Growing disk entries over time as more content is indexed
- Low misses relative to hits

### When to Clear the Cache

- **After changing embedding provider or model** — prevents dimension mismatches and stale cached vectors
- **Suspected cache corruption** — if embeddings seem incorrect or search quality degrades unexpectedly
- **To force fresh embeddings** — when you need to ensure all vectors reflect the current provider/model

```bash
# Clear with confirmation prompt
brainpalace cache clear

# Clear without prompt (use in scripts)
brainpalace cache clear --yes
```

### Cache is Automatic

No configuration is required. Embeddings are cached on first compute and reused on subsequent
reindexes of unchanged content (identified by SHA-256 hash). The cache complements the
ManifestTracker — files that haven't changed on disk won't need to recompute embeddings.

See the [API Reference](references/api_reference.md) for `GET /index/cache` and `DELETE /index/cache`
endpoint details, including response schemas.

---

## When Not to Use

This skill focuses on **searching and querying**. Do NOT use for:

- **Installation** - Use `configuring-brainpalace` skill
- **API key configuration** - Use `configuring-brainpalace` skill
- **Server setup issues** - Use `configuring-brainpalace` skill
- **Provider configuration** - Use `configuring-brainpalace` skill

**Scope boundary**: This skill assumes BrainPalace is already installed, configured, and the server is running with indexed documents.

---

## Best Practices

1. **Mode Selection**: BM25 for exact terms, Vector for concepts, Hybrid for comprehensive, Graph for relationships
2. **Threshold Tuning**: Start at 0.7, lower to 0.3-0.5 for more results
3. **Server Discovery**: Use `runtime.json` rather than assuming port 8000
4. **Resource Cleanup**: Run `brainpalace stop` when done
5. **Source Citation**: Always reference source filenames in responses
6. **Graph Queries**: Use graph mode for "what calls X", "what imports Y" patterns
7. **Traversal Depth**: Start with depth 2, increase to 3-4 for deeper chains
8. **File Type Presets**: Use `--include-type python,docs` instead of manual glob patterns
9. **Incremental Indexing**: Re-index without `--force` for efficient updates
10. **Injection Validation**: Always `--dry-run` injector scripts before full indexing
11. **Job Monitoring**: Use `brainpalace jobs --watch` for long-running index jobs
12. **BM25 Language**: Set the project language at init time (`brainpalace init --language de`); use `--language` per-query only when searching content in a different language than the project default

---

## Reference Documentation

| Guide | Description |
|-------|-------------|
| [BM25 Search](references/bm25-search-guide.md) | Keyword matching for technical queries |
| [Vector Search](references/vector-search-guide.md) | Semantic similarity for concepts |
| [Hybrid Search](references/hybrid-search-guide.md) | Combined keyword and semantic search |
| [Graph Search](references/graph-search-guide.md) | Knowledge graph and relationship queries |
| [Server Discovery](references/server-discovery.md) | Auto-discovery, multi-agent sharing |
| [Provider Configuration](references/provider-configuration.md) | Environment variables and API keys |
| [Integration Guide](references/integration-guide.md) | Scripts, Python API, CI/CD patterns |
| [API Reference](references/api_reference.md) | REST endpoint documentation |
| [Troubleshooting](references/troubleshooting-guide.md) | Common issues and solutions |

---

## Limitations

- Vector/hybrid/graph/multi modes require embedding provider configured
- Graph mode requires additional memory (~500MB extra)
- Supported formats: Markdown, PDF, plain text, code files (Python, JS, TS, Java, Go, Rust, C, C++)
- Not supported: Word docs (.docx), images
- Server requires ~500MB RAM for typical collections (~1GB with graph)
- Ollama requires local installation and model download
