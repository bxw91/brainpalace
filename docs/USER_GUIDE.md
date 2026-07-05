---
last_validated: 2026-07-05
---

# BrainPalace User Guide

This guide covers how to use BrainPalace for document indexing and semantic search using the Claude Code plugin.

## Table of Contents

- [Overview](#overview)
- [Plugin Commands](#plugin-commands)
- [Plugin Agents](#plugin-agents)
- [Search Modes](#search-modes)
- [Multi-Language Search (BM25)](#multi-language-search-bm25)
- [Two-Stage Retrieval with Reranking](#two-stage-retrieval-with-reranking)
- [Indexing](#indexing)
- [Folder Management](#folder-management)
- [File Type Presets](#file-type-presets)
- [Content Injection](#content-injection)
- [Chunk Eviction](#chunk-eviction)
- [File Watcher](#file-watcher)
- [Embedding Cache](#embedding-cache)
- [Job Queue](#job-queue)
- [Query History](#query-history)
- [Provider Configuration](#provider-configuration)
- [Multi-Project Support](#multi-project-support)
- [Runtime Autodiscovery](#runtime-autodiscovery)
- [Runtime Installation](#runtime-installation)
- [CLI Reference](#cli-reference)
- [Local Integration Check](#local-integration-check)
- [Troubleshooting](#troubleshooting)

---

## Overview

BrainPalace is a RAG (Retrieval-Augmented Generation) system that indexes and searches documentation and source code. The primary interface is the **Claude Code plugin** which provides:

| Component | Count | Description |
|-----------|-------|-------------|
| **Commands** | 34 | Slash commands for all operations |
| **Agents** | 5 | Intelligent assistants for complex tasks |
| **Skills** | 2 | Context for optimal search and configuration |

### How It Works

1. **Indexing**: Reads documents/code, splits into semantic chunks, generates embeddings
2. **Storage**: Stores chunks in ChromaDB with metadata for filtering
3. **Retrieval**: Finds similar chunks using hybrid search (semantic + keyword)
4. **GraphRAG**: Extracts entities and relationships for dependency queries

---

## Plugin Commands

### Search Commands

All retrieval is one command, `/brainpalace-query`, with a `--mode` flag:

_Add `--alpha 0.7` to tune hybrid vector/BM25 weighting._

<!--GENERATED:modes-->
| Command | Description | Best For |
|---------|-------------|----------|
| `/brainpalace-query --mode vector` | Semantic similarity search | Conceptual understanding |
| `/brainpalace-query --mode bm25` | Keyword matching | Exact terms, error codes |
| `/brainpalace-query` | Vector + BM25 fusion (default) | General questions |
| `/brainpalace-query --mode graph` | Knowledge graph relationships (empty unless the graph is built) | Relationships, dependencies |
| `/brainpalace-query --mode multi` | Fusion of vector + BM25 + graph via RRF | Comprehensive recall |
| `/brainpalace-query --mode compute` | Set-level aggregation over typed numeric records | Aggregates over your sessions (sum/count/avg, by week/month, superlatives) |
| `/brainpalace-query --mode scan` | Deterministic term counts over archived session transcripts (empty when the session archive is off) | Utterance history over sessions |
| `/brainpalace-query --mode absence` | Anti-join over typed records (empty when no two stored values resolve) | Subjects present under one value but absent under another |
| `/brainpalace-query --mode timeline` | Edge-validity/supersession history walk (empty when the entity resolves to no graph node) | How a belief/fact evolved over time |
<!--/GENERATED-->

**Time-decay (recency).** All search modes rank **newer** content higher by
default — fresh sessions, recent commits, and just-edited code beat stale matches
at equal relevance (gentle 90-day half-life). Disable it for a single query with
`brainpalace query "..." --no-time-decay`, or globally with
`BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS=0`. See
[CONFIGURATION](CONFIGURATION.md#time-decay-ranking).

### Memory Commands

Curated, git-tracked facts that get boosted into search results. Full guide:
[MEMORY.md](MEMORY.md).

| Command | Description |
|---------|-------------|
| `brainpalace remember "<fact>" [--tags] [--section]` | Save a durable fact |
| `brainpalace recall "<query>"` | Search the memory namespace only |
| `brainpalace memories list\|show\|delete\|obsolete` | Manage memories |
| `brainpalace context` | Print the session-start context block (for a SessionStart hook) — see [SESSION_CONTEXT.md](SESSION_CONTEXT.md) |

### Server Commands

| Command | Description |
|---------|-------------|
| `/brainpalace-start` | Start server (auto-port allocation) |
| `/brainpalace-stop` | Stop the running server |
| `/brainpalace-status` | Check health and document count |
| `/brainpalace-list` | List all running instances |
| `/brainpalace-index` | Index documents or code |
| `/brainpalace-reset` | Clear the index |
| `/brainpalace-jobs` | Manage indexing job queue |

### Index Management Commands

| Command | Description |
|---------|-------------|
| `/brainpalace-folders` | Manage indexed folders (list, add, remove) |
| `/brainpalace-inject` | Inject custom metadata into chunks during indexing |
| `/brainpalace-types` | List available file type presets for indexing |
| `/brainpalace-cache` | View embedding cache metrics or clear the cache |

### Setup Commands

| Command | Description |
|---------|-------------|
| `/brainpalace-setup` | Complete guided setup wizard |
| `/brainpalace-install` | Install pip packages |
| `/brainpalace-install-agent` | Install for different AI runtimes (Claude, OpenCode, Gemini, Codex) |
| `/brainpalace-init` | Initialize project directory |
| `/brainpalace-config` | View/edit configuration |
| `/brainpalace-verify` | Verify configuration |

### Provider Configuration

Embedding and summarization providers are configured through the
`/brainpalace-config` wizard (there are no separate per-provider commands).

### Diagnosing setup problems — `brainpalace doctor`

When something isn't working, run the diagnostic command first:

```bash
brainpalace doctor
```

It prints a table checking Python version, CLI install, project
initialization (and *which* rule selected the project root — useful in
monorepos), provider config, required API keys, optional dependencies,
`.gitignore` hygiene, and whether the server is reachable. It exits non-zero
on any critical failure, so it works in scripts:

```bash
brainpalace doctor || brainpalace init
```

When the server is reachable, doctor also reports three **scale checks** that
surface growth limits before they bite (all are advisory — they never change
the exit code):

| Check | What it tells you |
|-------|-------------------|
| `graph_size` | Warns when the simple in-memory graph (JSON-persisted) grows past a node ceiling — boot/memory cost grows with it. Auto-clears once a persistent graph backend is active. |
| `index_staleness` | Warns when source files on disk are more than N days newer than the last index — recall may miss recent edits (watcher off/crashed, or edited while the server was down). |
| `collection_sizes` | One-line per-collection chunk counts: `code`, `docs`, `memories` (and `sessions` / `git` once those collections exist). A fast "where did my chunks go" answer. |

Two env knobs tune the thresholds:

| Env var | Default | Effect |
|---------|---------|--------|
| `BRAINPALACE_DOCTOR_GRAPH_MAX_NODES` | `25000` | Node ceiling (entities + relationships) before `graph_size` warns. |
| `BRAINPALACE_DOCTOR_STALE_DAYS` | `7` | Days the tree may lead the index before `index_staleness` warns. |

| Flag | Effect |
|------|--------|
| `--json` | Emit a machine-readable report (used by the plugin setup check). |
| `--fix` | Apply safe, idempotent, offline fixes only — add `.brainpalace/` to `.gitignore`, create a stub state dir. Never touches API keys, the network, or your code. Re-runs the report afterward. |
| `--url <URL>` | Probe a specific server URL instead of the auto-resolved one. |

Any command that can't reach the server also prints a context-sensitive
doctor hint, so you're pointed at `brainpalace doctor` (or `brainpalace
init`) automatically.

---

## Plugin Agents

BrainPalace includes five intelligent agents that handle complex, multi-step tasks:

### Search Assistant

Performs multi-step searches across different modes and synthesizes answers.

**Triggers**: "Find all references to...", "Search for...", "What files contain..."

**Example**:
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

**Triggers**: "Research how...", "Investigate...", "Analyze the architecture of..."

**Example**:
```
You: "Research how error handling is implemented"

Research Assistant:
1. Identifies error handling patterns in docs
2. Finds exception classes and try/catch blocks
3. Traces error propagation through call graph
4. Synthesizes findings with code references
```

### Setup Assistant

Guided installation, configuration, and troubleshooting.

**Triggers**: "Help me set up BrainPalace", "Configure...", "Why isn't... working"

**Example**:
```
You: "Help me set up BrainPalace with Ollama"

Setup Assistant:
1. Checks if Ollama is installed
2. Verifies embedding model is pulled
3. Configures provider settings
4. Tests the configuration
5. Reports success or guides through fixes
```

### Chat Session Extractor

Extracts durable knowledge — a summary, decisions, and knowledge-graph triplets —
from a finished AI-coding session and submits it to BrainPalace memory.

**Triggers**: runs over a completed session transcript (e.g. via the session
extraction hook), not by a conversational request.

### Memory Curator

Distils recent session decisions into curated memory and prunes or merges stale
or duplicate memories, on the subscription model.

**Triggers**: scheduled/curation runs over the memory namespace.

---

## Search Modes

### HYBRID (Default)

Combines semantic similarity with keyword matching. Best for general questions.

```
/brainpalace-query "how does the caching system work"
```

Adjust the balance with `--alpha`:
- `--alpha 0.7` - More semantic (conceptual queries)
- `--alpha 0.3` - More keyword (specific terms)

```
/brainpalace-query --mode hybrid "authentication flow" --alpha 0.7
```

### VECTOR (Semantic)

Pure embedding-based search. Best for conceptual understanding.

```
/brainpalace-query --mode vector "explain the overall architecture"
```

### BM25 (Keyword)

TF-IDF based search. Best for exact terms, function names, error codes.

```
/brainpalace-query --mode bm25 "NullPointerException"
/brainpalace-query --mode bm25 "getUserById"
```

BM25 tokenizes each document in **its own natural language** (stemming +
stopwords), so keyword search works precisely for non-English content. See
[Multi-Language Search (BM25)](#multi-language-search-bm25).

### GRAPH (Knowledge Graph)

Traverses entity relationships. Best for dependency and relationship queries.

```
/brainpalace-query --mode graph "what classes use AuthService"
/brainpalace-query --mode graph "what calls the validate function"
```

### MULTI (Fusion)

Combines all modes using Reciprocal Rank Fusion. Best for maximum recall.

```
/brainpalace-query --mode multi "everything about data validation"
```

### COMPUTE (Set-level aggregation)

Answers numeric questions over the typed records accumulated from your
AI-coding sessions: counts, sums, averages, and superlatives. Returns
aggregation rows, not text chunks. Best for questions like "how many files did I
touch last week?" or "which week had the most decisions?".

```bash
brainpalace query "how many files did I touch last week" --mode compute
brainpalace query "which week had the most tools used" --mode compute
brainpalace query "total decisions this month" --mode compute
```

**Auto-routing:** `hybrid` (the default) automatically tries compute first when
the query contains a set-level tell (`"how many"`, `"total"`, `"which week had
the most"`, etc.). If compute returns rows they are returned immediately;
otherwise the query falls back to normal hybrid retrieval. You can also force
`--mode compute` explicitly.

Records are populated from session extraction — compute is empty until
`extraction.mode != off`. Full details: [COMPUTE.md](COMPUTE.md).

---

## Multi-Language Search (BM25)

BrainPalace tokenizes each document with its **own natural-language analyzer**
(normalize → tokenize → drop stopwords → stem/lemmatize) before BM25 scoring, so
keyword and hybrid search are accurate regardless of the language your docs are
written in. ~27 Snowball/PyStemmer languages are supported out of the box
(`en`, `de`, `fr`, `es`, `ru`, `it`, `pt`, `nl`, `sv`, `fi`, `hu`, `ro`, `tr`,
`ar`, …) plus a custom Croatian (`hr`) stemmer. Unknown codes fall back to
English. (Full list + "how to add a language": see the project README.)

### Set the project language

`bm25:` block in `.brainpalace/config.yaml`:

```yaml
bm25:
  language: en               # ISO 639-1 project default (default: en)
  engine: stem               # stem (default) | lemma
  detect: false              # opt-in per-document language detection
  detect_min_confidence: 0.6
```

Or via the CLI:

```bash
brainpalace init --language hr --bm25-engine stem    # set at init
brainpalace folders add ./docs --language hr         # sets the project default
brainpalace status                                   # shows active language + engine
```

### Override the language per query

```bash
brainpalace query "liječnik" --mode bm25 --language hr
```

The `--language` flag (also exposed on the MCP `query` tool) overrides
tokenization for that one query; it defaults to the project `bm25.language`.

### Engines

- **`stem`** (default) — Snowball/PyStemmer stemmers; covers all supported languages.
- **`lemma`** — higher-accuracy lemmatization for Croatian via
  `pip install 'brainpalace[lemma-hr]'` (uses `simplemma`). For other languages,
  `stem` is correct.

> **Reindex note:** changing `language`/`engine` changes tokenization. The BM25
> index auto-rebuilds from its stored corpus on the next server start to keep
> index and query in sync. To re-detect per-document languages (`detect: true`),
> re-run indexing.

---

## Two-Stage Retrieval with Reranking

BrainPalace can optionally use two-stage retrieval to improve search precision by 15-20%.

### How It Works

**Without Reranking (Default)**:
1. Query is embedded using the embedding model
2. Vector similarity search finds top_k most similar documents
3. Results are returned

**With Reranking Enabled**:
1. Query is embedded using the embedding model
2. Vector + BM25 hybrid search retrieves 10x more candidates
3. Cross-encoder model scores each candidate for relevance to the query
4. Results are reordered by cross-encoder score
5. Top_k results are returned

### Why Reranking Helps

Embedding models (bi-encoders) are fast but approximate. They encode the query and documents separately, then compare vectors. This can miss nuanced relevance.

Cross-encoders process the query AND document together, allowing the model to attend across both texts. This is slower but more accurate.

### When to Enable Reranking

Enable reranking when:
- Precision matters more than latency
- Queries are complex or nuanced
- Initial results seem "close but not quite right"

Keep reranking disabled when:
- Latency is critical (real-time search)
- Running on resource-constrained hardware
- Search quality is already acceptable

### Configuration

Enable with environment variable:
```bash
export ENABLE_RERANKING=true
```

Or in config.yaml:
```yaml
reranker:
  provider: sentence-transformers
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
```

### Provider Choices

**sentence-transformers (Recommended)**:
- Uses HuggingFace CrossEncoder models
- Downloads model on first use (~50MB)
- Fast inference (~50ms for 100 candidates)

**ollama (Fully Local)**:
- Uses Ollama chat completions for scoring
- No external downloads
- Slower (~500ms for 100 candidates)
- Requires Ollama running locally

### Response Fields

When reranking is enabled, results include additional metadata:
- `rerank_score`: Cross-encoder relevance score
- `original_rank`: Position before reranking (1-indexed)

---

## Indexing

### Index Documentation

```
/brainpalace-index ./docs
```

### Index Code and Documentation

```
/brainpalace-index .
```

### Index Specific Languages

```
/brainpalace-index ./src --languages python,typescript
```

### Index with File Type Presets

```
/brainpalace-index ./src --include-type python
/brainpalace-index ./project --include-type python,docs
```

### Supported Languages

BrainPalace supports AST-aware chunking for:
- **Python** (.py)
- **TypeScript** (.ts, .tsx)
- **JavaScript** (.js, .jsx)
- **Java** (.java)
- **Go** (.go)
- **Rust** (.rs)
- **C** (.c, .h)
- **C++** (.cpp, .hpp, .cc)
- **C#** (.cs, .csx)
- **Object Pascal** (.pas, .pp, .lpr, .dpr, .dpk)

Other languages (including Kotlin and Swift, which are detected and indexed) use
intelligent text-based chunking.

### Check Index Status

```
/brainpalace-status
```

### Clear and Rebuild Index

```
/brainpalace-reset
/brainpalace-index .
```

---

## Folder Management

BrainPalace tracks indexed folders and provides commands to list, add, and remove them. Folders are persisted in a JSONL manifest that enables incremental re-indexing -- only changed files are processed on subsequent runs.

### List Indexed Folders

Show all indexed folders with chunk counts and last-indexed timestamps:

```
brainpalace folders list
```

Example output:
```
Folder Path              Chunks  Last Indexed
~/projects/<your-project>/docs   312     2026-02-24T12:00:00
~/projects/<your-project>/src    1024    2026-02-24T13:30:00
```

### Add a Folder

Queue an indexing job for a folder. Supports all indexing options:

```
brainpalace folders add ./docs
brainpalace folders add ./src
brainpalace folders add ./src --include-type python,docs
brainpalace folders add ./docs --force
```

Adding an already-indexed folder triggers incremental re-indexing (only changed files are processed). Use `--force` to bypass the manifest and re-index everything.

### Remove a Folder

Remove all indexed chunks associated with a folder:

```
brainpalace folders remove ./old-docs
brainpalace folders remove ./old-docs --yes   # skip confirmation
```

The folder does not need to exist on disk to be removed from the index.

### File Watcher Integration

When adding a folder, you can enable automatic re-indexing via the file watcher (see [File Watcher](#file-watcher) section). Folders with `watch_mode=auto` are monitored for changes and re-indexed automatically.

### Plugin Command

Use the plugin command for the same operations:

```
/brainpalace-folders list
/brainpalace-folders add ./src
/brainpalace-folders remove ./old-docs --yes
```

---

## File Type Presets

File type presets are named groups of glob patterns that simplify indexing. Instead of specifying individual file extensions, use a preset name with the `--include-type` flag.

### Available Presets

| Preset | Extensions |
|--------|------------|
| `python` | `*.py`, `*.pyi`, `*.pyw` |
| `javascript` | `*.js`, `*.jsx`, `*.mjs`, `*.cjs` |
| `typescript` | `*.ts`, `*.tsx` |
| `go` | `*.go` |
| `rust` | `*.rs` |
| `java` | `*.java` |
| `csharp` | `*.cs` |
| `pascal` | `*.pas`, `*.pp`, `*.lpr`, `*.dpr`, `*.dpk` |
| `object-pascal` | `*.pas`, `*.pp`, `*.lpr`, `*.dpr`, `*.dpk` |
| `c` | `*.c`, `*.h` |
| `cpp` | `*.cpp`, `*.hpp`, `*.cc`, `*.hh` |
| `web` | `*.html`, `*.css`, `*.scss`, `*.jsx`, `*.tsx` |
| `docs` | `*.md`, `*.txt`, `*.rst`, `*.pdf` |
| `text` | `*.md`, `*.txt`, `*.rst` |
| `pdf` | `*.pdf` |
| `code` | All programming language extensions combined |

### Usage Examples

```bash
# Index only Python files
brainpalace index ./src --include-type python

# Index Python and documentation files
brainpalace index ./project --include-type python,docs

# Index all code files
brainpalace index ./repo --include-type code

# Combine presets with custom patterns
brainpalace index ./project --include-type typescript --include-patterns "*.json"
```

### Viewing Available Presets

Use the types command to see all presets:

```
/brainpalace-types
```

Presets can be combined with commas: `--include-type python,docs`. The `code` preset is a union of all individual language presets.

---

## Content Injection

Content injection enriches chunk metadata during indexing using custom Python scripts or static JSON metadata files. Injectors run after chunking but before embedding generation (step 2.5 in the pipeline), so enriched metadata is stored alongside vectors in the index.

### Script Injection

Provide a Python script that exports a `process_chunk` function:

```bash
brainpalace inject ./docs --script enrich.py
```

The script must define:

```python
def process_chunk(chunk: dict) -> dict:
    """Enrich a single chunk with custom metadata."""
    chunk["project"] = "my-project"
    chunk["team"] = "backend"
    return chunk
```

**Input keys available:** `chunk_id`, `content`, `source`, `language`, `start_line`, `end_line`, `summary`

**Constraints:**
- Values must be scalars (str, int, float, bool) -- lists and dicts are stripped for ChromaDB compatibility
- Core schema keys (`chunk_id`, `source`, etc.) cannot be overwritten
- Exceptions are caught per-chunk and logged as warnings (the pipeline continues)

### Folder Metadata Injection

Merge a static JSON file into every chunk from a folder:

```bash
brainpalace inject ./src --folder-metadata project-meta.json
```

JSON format:
```json
{
  "project": "my-project",
  "team": "backend",
  "version": "2.0"
}
```

### Dry-Run Validation

Validate an injector against sample chunks without actually indexing:

```bash
brainpalace inject ./docs --script enrich.py --dry-run
```

### Plugin Command

```
/brainpalace-inject ./docs --script enrich.py
/brainpalace-inject ./src --folder-metadata project-meta.json
/brainpalace-inject ./docs --script enrich.py --dry-run
```

At least one of `--script` or `--folder-metadata` must be provided.

---

## Chunk Eviction

When files change or are removed, BrainPalace automatically evicts stale chunks from the index during the next indexing run. This is powered by the manifest tracker, which records per-file checksums, modification times, and chunk IDs.

### How It Works

1. **Manifest comparison**: On each indexing run, the current filesystem state is compared against the prior folder manifest.
2. **Diff computation**: Files are categorized as added, changed, deleted, or unchanged.
   - **mtime check first**: If the file modification time is unchanged, the file is skipped (fast path).
   - **Checksum verification**: If mtime changed, a SHA-256 content checksum confirms whether the content actually changed (handles `touch`, `git checkout`, etc.).
3. **Bulk eviction**: Chunk IDs for deleted and changed files are removed from the storage backend in bulk.
4. **Re-indexing**: Only added and changed files are processed, saving time on large codebases.

### Force Mode

Use `--force` to bypass the manifest and re-index all files:

```bash
brainpalace index ./src --force
```

Force mode evicts all prior chunks for the folder and processes every file fresh.

### Manifest Storage

Manifests are stored as JSON files in the state directory:
```
.brainpalace/manifests/<sha256(folder_path)>.json
```

Each manifest records per-file checksums, mtimes, and chunk IDs for targeted deletion.

---

## File Watcher

The file watcher service monitors indexed folders for changes and triggers automatic incremental re-indexing. It uses `watchfiles` (based on the Rust `notify` crate) for efficient filesystem event detection.

### How It Works

- One asyncio task is created per watched folder
- When file changes are detected, an incremental indexing job is enqueued
- Jobs are deduplicated -- if a job for the same folder is already pending, no duplicate is created
- Changes are debounced to avoid rapid re-indexing (default: 30 seconds)

### Watch Modes

| Mode | Behavior |
|------|----------|
| `off` | No automatic re-indexing (default) |
| `auto` | Watch for changes and re-index automatically |

### Configuration

Configure the file watcher via `config.yaml`:

```yaml
file_watcher:
  default_debounce_seconds: 30  # Global debounce interval
```

Per-folder debounce can be set when adding a folder with watch mode enabled.

**Post-enqueue cooldown:** after a watcher-triggered reindex job is enqueued, further
file-change events for the same folder are suppressed for a minimum interval. This
collapses bursts of delayed inotify events (e.g. editor save + temp file cleanup)
into a single job.

```bash
# Default: 10 seconds. Set 0 to disable.
export BRAINPALACE_WATCH_POST_ENQUEUE_COOLDOWN_SECONDS=10
```

### Ignored Directories

The watcher automatically ignores common non-source directories: `.git/`, `__pycache__/`, `node_modules/`, `.venv/`, `dist/`, `build/`, `.next/`, `.nuxt/`, `coverage/`, `htmlcov/`.
`.brainpalace/` is always excluded (hardcoded) — server state writes never trigger reindex loops.

### Jobs Triggered by Watcher

Watcher-triggered jobs are tagged with `source="auto"` to distinguish them from manual indexing jobs. They always use `force=False` (incremental mode via the manifest tracker).

---

## Embedding Cache

BrainPalace automatically caches embeddings in a two-layer architecture to avoid redundant API calls. The cache is transparent -- it requires no setup and works with any embedding provider.

### Architecture

- **Layer 1 (Memory)**: In-memory LRU cache with fixed capacity (default: 10,000 entries). Sub-millisecond lookups with zero I/O.
- **Layer 2 (Disk)**: aiosqlite SQLite database in WAL mode. Single-digit millisecond lookups. Persists across server restarts. Default limit: 500 MB (~42,000 entries at 3,072 dimensions).

### Cache Key Format

Keys are computed as `SHA-256(content_text):provider:model:dimensions`. This ensures cached embeddings are invalidated when the embedding provider or model changes.

### Provider Change Detection

On startup, the cache compares the current provider fingerprint against the stored fingerprint. If they differ, all cached embeddings are automatically cleared to prevent dimension mismatches.

### Cache Management Commands

Use the CLI or plugin command to view cache status and clear the cache:

```bash
# View cache metrics
brainpalace cache status

# View metrics as JSON
brainpalace cache status --json

# Clear the cache (prompts for confirmation)
brainpalace cache clear

# Clear without confirmation
brainpalace cache clear --yes
```

Plugin commands:
```
/brainpalace-cache status
/brainpalace-cache clear --yes
```

### Interpreting Cache Metrics

| Metric | Description |
|--------|-------------|
| Entries (disk) | Total embeddings persisted in the SQLite database |
| Entries (memory) | Embeddings in the in-memory LRU (fastest tier) |
| Hit Rate | Percentage of lookups served from cache (higher is better) |
| Hits | Total successful cache lookups this session |
| Misses | Cache misses (embedding computed via API) |
| Size | Disk space used by the cache database |

A healthy cache has a hit rate above 80% after the first full indexing cycle.

### When to Clear the Cache

- After changing embedding provider or model (prevents dimension mismatches)
- If embeddings seem incorrect or queries return poor results
- To force fresh embeddings after significant content changes

---

## Job Queue

As of v3.0.0, indexing operations are queued and processed asynchronously.

### How It Works

1. **Submit**: `POST /index` returns immediately with a job ID
2. **Queue**: Jobs are stored in `.brainpalace/jobs/index_queue.jsonl`
3. **Process**: Background worker processes jobs sequentially
4. **Track**: Poll job status or use CLI `--watch` option

### CLI Jobs Commands

```bash
# List all jobs
brainpalace jobs

# Watch queue with live updates
brainpalace jobs --watch

# Get job details
brainpalace jobs job_abc123def456

# Cancel a job
brainpalace jobs job_abc123def456 --cancel
```

### Job States

| Status | Description |
|--------|-------------|
| `pending` | Queued, waiting to run |
| `running` | Currently processing |
| `done` | Completed successfully |
| `failed` | Failed with error |
| `cancelled` | Cancelled by user |

### Deduplication

The queue automatically deduplicates identical requests. If you submit the same folder with the same options while a job is pending or running, you get back the existing job ID.

### Polling for Completion

```bash
# Check if indexing is done
brainpalace status --json | jq '.indexing.indexing_in_progress'

# Or poll specific job
brainpalace jobs job_abc123 | grep status
```

---

## Query History

Every successful query is recorded (with truncated results) in a per-project
SQLite log at `.brainpalace/query_log.db`. This powers the dashboard
**Queries** tab — browse recent queries, inspect their results, and replay any
query against the live server.

### Configuration

Add a `query_log:` section to your project `config.yaml` (defaults shown):

```yaml
query_log:
  enabled: true        # ON by default; set false to stop recording
  retention_days: 7    # purge rows older than N days on startup; 0 = keep forever
```

`retention_days` is enforced by a purge on server startup. A value of `0`
(or any non-positive number) keeps history forever.

### Kill switch

Set `QUERY_LOG_ENABLED=false` in the environment to hard-disable query logging
regardless of the project `config.yaml` setting.

> ⚠️ The log stores the query text plus truncated result snippets/paths. It
> does not store full document contents, but treat it like any other index
> artifact under `.brainpalace/` (gitignored, per-project).

### Endpoints

The project server exposes:

- `GET /query/history` — recent queries (newest first), filterable by
  `since`, `mode`, `contains`, `limit`, `offset`. Omits the result payload.
- `GET /query/history/{qid}` — a single logged query including its truncated
  results.
- `GET /health/logs` — a bounded tail of the server log file
  (`.brainpalace/server.log`), filterable by `lines` and `level`.

---

## Provider Configuration

BrainPalace supports pluggable providers for embeddings and summarization.

### Configure Providers Interactively

```
/brainpalace-config
```

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

---

## Multi-Project Support

BrainPalace supports multiple isolated instances for different projects.

### Initialize a Project

```
/brainpalace-init
```

Creates `.brainpalace/` with project-specific configuration.

### Start Project Server

```
/brainpalace-start
```

Automatically allocates a unique port (no conflicts).

### List Running Instances

```
/brainpalace-list
```

Shows all running BrainPalace servers across projects.

### Work from Subdirectories

Commands automatically resolve the project root:

```
cd src/deep/nested/directory
/brainpalace-status  # Finds the parent project's server
```

---

## Runtime Autodiscovery

The CLI automatically discovers the server URL without manual configuration.

### How It Works

When you run `brainpalace start`, the server writes a `runtime.json` file:

```
.brainpalace/runtime.json
```

Contents:
```json
{
  "base_url": "http://127.0.0.1:49321",
  "port": 49321,
  "bind_host": "127.0.0.1",
  "pid": 12345,
  "started_at": "2026-02-03T10:00:00Z",
  "foreground": false
}
```

### CLI Resolution Order

The CLI resolves the server URL in this priority:

1. **Environment variable**: `BRAINPALACE_URL`
2. **Runtime file**: `.brainpalace/runtime.json` (searches cwd upward)
3. **Owning project, server down**: if an owning `.brainpalace/` project is found but no live server validates, the CLI raises `ServerNotReachableError` (it does **not** fall through to config.yaml)
4. **Runtime file fallback**: default of `http://127.0.0.1:8000` when no owning project is found
5. **Default**: `http://127.0.0.1:8000`

### Config Discovery Order

Config files are searched in this order:

1. `.brainpalace/config.yaml` (cwd, then walk upward)
2. `~/.config/brainpalace/config.yaml` (XDG config)
3. `~/.brainpalace/config.yaml` (legacy, deprecated)
4. Environment variable: `BRAINPALACE_CONFIG`

### Example Workflow

```bash
# Start server (writes runtime.json automatically)
brainpalace start

# CLI auto-discovers server URL - no --url flag needed
brainpalace status
brainpalace index ./docs
brainpalace query "search term"
```

---

## Runtime Installation

BrainPalace can be installed for multiple AI runtimes. The `install-agent` command converts the canonical Claude plugin format into the target runtime's native format.

### Supported Runtimes

| Runtime | Command | Default Directory |
|---------|---------|-------------------|
| Claude Code | `--agent claude` | `.claude/plugins/brainpalace/` |
| OpenCode | `--agent opencode` | `.opencode/plugins/brainpalace/` |
| Gemini CLI | `--agent gemini` | `.gemini/plugins/brainpalace/` |
| Codex | `--agent codex` | `.codex/skills/brainpalace/` |
| Any skill-based | `--agent skill-runtime --dir <path>` | (required) |

### Installation Examples

```bash
# Install for Claude Code (default)
brainpalace install-agent --agent claude

# Install for Codex (generates AGENTS.md at project root)
brainpalace install-agent --agent codex

# Install for any skill-based runtime (e.g., Qwen, Cursor)
brainpalace install-agent --agent skill-runtime --dir ./my-skills

# Preview what would be installed
brainpalace install-agent --agent codex --dry-run

# Install globally (user-level)
brainpalace install-agent --agent claude --global

# JSON output for automation
brainpalace install-agent --agent codex --json
```

### Skill-Runtime Converter

The `skill-runtime` converter flattens all plugin artifacts into skill directories:

- **Commands** become individual skill directories with `SKILL.md`
- **Agents** become orchestration skill directories referencing dependent skills
- **Skills** are copied with references intact
- **Templates** are placed in `brainpalace-setup/assets/`
- **Scripts** are placed in `brainpalace-verify/scripts/`

### Codex Adapter

The `codex` adapter is a preset built on `skill-runtime` that also:

- Installs to `.codex/skills/brainpalace/` by default
- Generates/updates `AGENTS.md` at the project root
- Adds invocation guidance headers to each skill
- Uses HTML comment markers for idempotent AGENTS.md updates

### Adding New Runtime Support

To add support for a new runtime, implement the `RuntimeConverter` protocol:

```python
from brainpalace_cli.runtime.converter_base import RuntimeConverter

class MyConverter:
    @property
    def runtime_type(self) -> RuntimeType: ...
    def convert_command(self, command: PluginCommand) -> str: ...
    def convert_agent(self, agent: PluginAgent) -> str: ...
    def convert_skill(self, skill: PluginSkill) -> str: ...
    def install(self, bundle: PluginBundle, target: Path, scope: Scope) -> list[Path]: ...
```

Then register it in `install_agent.py`'s `CONVERTERS` dict.

---

## MCP Integration (opt-in)

Non-Claude-Code AI clients can talk to BrainPalace through the Model Context
Protocol. BrainPalace ships an opt-in stdio MCP server — `brainpalace mcp` — that
forwards calls to the existing HTTP server. The v1 tool surface is nine tools:
`query`, `status`, `whoami`, `folders_list`, `jobs_list`, `recall`,
`session_context`, and `ai_guide` are read-only; `memorize` writes a curated
memory. Most tools accept an optional `path` argument so the long-lived shim is
not pinned to its spawn-time directory.

Supported clients with copy-paste config snippets:

- **Claude Code** (opt-in — the plugin's skill + slash commands remain the
  default)
- **VS Code native** (GitHub Copilot agent mode, `.vscode/mcp.json`)
- **Cursor**
- **Kilo Code** v7.x
- **Cline**
- **Continue**
- **Zed**

The `--ensure-server` flag auto-starts the HTTP server for the spawn-time
project if discovery finds none — recommended for every non-Claude-Code
client. Claude Code already has a start hook so the flag is omitted there.

Full per-client setup, environment gotchas (VS Code PATH inheritance,
per-client timeout tuning), and troubleshooting live in
[`docs/MCP_SETUP.md`](MCP_SETUP.md).

---

## CLI Reference

For advanced users or automation, the CLI provides direct access:

### Installation

Install via the one-line installer (pipx-based; installs
`brainpalace-cli`, which pulls the `brainpalace-rag` server into the
same venv):

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
```

Or directly: `pipx install brainpalace-cli`.

### Common Commands

```bash
# Initialize project
brainpalace init                             # full setup: confirm, then start + index + sessions
brainpalace init --yes                       # full setup, no prompt (CI/scripts)
brainpalace init --no-start                  # config only (no server, no indexing)
brainpalace init --no-sessions               # everything except embedding transcripts
brainpalace init --force-monorepo-root       # override workspace-root guard

# Configure providers
brainpalace config wizard                    # this project's .brainpalace/config.yaml
brainpalace config wizard --global           # configure providers once, globally
                                             #   (~/.config/brainpalace/config.yaml — every project inherits it)

# Start/stop server
brainpalace start          # Backgrounds by default; also brings up the web
                           #   dashboard on Python 3.12+ and prints its URL
                           #   (opens a browser only when it launches one)
brainpalace start --foreground  # Run in foreground
brainpalace start --no-dashboard  # Don't auto-start the dashboard this run
brainpalace stop
brainpalace stop --url http://127.0.0.1:49321  # stop a specific server by URL

# Index documents
brainpalace index ./docs           # code + docs (default)
brainpalace index ./docs --no-code # doc-only (opt-out of code indexing)

# Index with file type presets
brainpalace index ./src --include-type python

# Folder management
brainpalace folders list
brainpalace folders add ./src
brainpalace folders remove ./old-docs --yes

# Content injection
brainpalace inject ./docs --script enrich.py
brainpalace inject ./src --folder-metadata project-meta.json

# Query
brainpalace query "your question" --mode hybrid

# Job management (v3.0+)
brainpalace jobs           # List all jobs
brainpalace jobs --watch   # Watch with live updates
brainpalace jobs JOB_ID    # Job details
brainpalace jobs JOB_ID --cancel  # Cancel job

# Cache management
brainpalace cache status
brainpalace cache clear --yes

# File type presets
brainpalace types list

# Runtime installation
brainpalace install-agent --agent claude
brainpalace install-agent --agent codex
brainpalace install-agent --agent skill-runtime --dir ./skills

# Status
brainpalace status
brainpalace list
```

### Query Options

```bash
# Search modes
brainpalace query "term" --mode vector
brainpalace query "term" --mode bm25
brainpalace query "term" --mode hybrid --alpha 0.7
brainpalace query "term" --mode graph
brainpalace query "term" --mode multi

# Result tuning
brainpalace query "term" --top-k 10 --threshold 0.3

# Filtering
brainpalace query "term" --source-types code
brainpalace query "term" --languages python,typescript

# Output formats
brainpalace query "term" --json
brainpalace query "term" --scores
```

---

## Local Integration Check

Before releasing or after major changes, run the local integration check to validate E2E functionality.

### Running the Check

```bash
./scripts/local_integration_check.sh
```

Or using Task:

```bash
task local-integration
```

### What It Validates

1. **Server startup**: Verifies server starts and writes `runtime.json`
2. **Runtime autodiscovery**: CLI finds server URL from `runtime.json`
3. **Job queue**: Indexing job completes without 409/500 errors
4. **Query**: Returns valid HTTP 200 response
5. **CLI commands**: `brainpalace jobs` works correctly

### Expected Output

```
=== BrainPalace Local Integration Check ===
Step 1: Cleaning up stray processes...
Step 2: Cleaning up old state...
Step 3: Starting server in foreground...
Step 4: Checking runtime.json...
  Found runtime.json
  Server URL: http://127.0.0.1:49321
Step 5: Waiting for health endpoint...
  Server is healthy!
...
=== Integration Check PASSED ===
```

### Troubleshooting Failed Checks

If the check fails:

1. **runtime.json not found**: Server failed to start - check for port conflicts
2. **Job failed**: Check server logs in `.brainpalace/logs/`
3. **Query failed**: Index may be empty - verify test data was created

---

## Troubleshooting

### Server Not Running

```
/brainpalace-status
```

If not running:
```
/brainpalace-start
```

### No Results Found

1. Check document count: `/brainpalace-status`
2. If 0 documents, re-index: `/brainpalace-index ./docs`
3. Try lowering threshold: `/brainpalace-query "term" --threshold 0.3`
4. Try different search mode: `/brainpalace-query --mode bm25 "exact term"`

### Configuration Issues

```
/brainpalace-verify
```

This checks:
- Package installation
- API key configuration
- Server connectivity
- Provider setup

### Provider Errors

```
/brainpalace-config
```

Verify your API keys are set correctly for the selected provider.

### Reset Everything

```
/brainpalace-reset
/brainpalace-init
/brainpalace-start
/brainpalace-index .
```

---

## `.gitignore` Support

The indexer and file watcher honour every `.gitignore` file under a project
root by default — including nested `.gitignore` files and negation rules
(`!keep.log`). This applies BOTH to the initial index build and to ongoing
file-watcher events: a file matched by `.gitignore` is never indexed and
never triggers a reindex.

Precedence (union — anything ignored by any source is excluded):

1. `ALWAYS_EXCLUDED_DIR_NAMES` (`.brainpalace` — hardcoded).
2. `DocumentLoader.DEFAULT_EXCLUDE_PATTERNS` (built-in).
3. Project `config.yaml` `indexing.exclude_patterns` (overrides #2 if present).
4. Project `.gitignore` files at any depth.

### Opting Out

Set the server environment variable:

```bash
export BRAINPALACE_HONOR_GITIGNORE=false
```

Then restart the server. Indexing falls back to #1 + #2 + #3 only.

---

## Updating an Existing Project's Defaults

An existing project keeps its `.brainpalace/config.yaml` settings. The defaults
(`--include-code` ON, `graphrag.enabled: true` in `config.yaml`) apply to fresh
`brainpalace init` runs.

To apply new defaults to an existing project:

```bash
# Option A: re-run init with --force to overwrite config.yaml
cd /path/to/project
rm .brainpalace/config.yaml       # remove old config (optional — saves provider keys)
brainpalace init --force           # writes new default config.yaml

# Option B: enable graph indexing interactively
brainpalace config wizard          # pick option 4 (AST code only, no LLM cost)
```

After updating, restart the server and reindex:

```bash
brainpalace stop
brainpalace start
brainpalace index .
```

---

## Next Steps

- [Quick Start](QUICK_START.md) - Get running in minutes
- [Plugin Guide](PLUGIN_GUIDE.md) - All 34 commands in detail
- [API Reference](API_REFERENCE.md) - REST API documentation
- [GraphRAG Guide](GRAPHRAG_GUIDE.md) - Knowledge graph features
- [Provider Configuration](../brainpalace-plugin/skills/using-brainpalace/references/provider-configuration.md) - Provider setup
