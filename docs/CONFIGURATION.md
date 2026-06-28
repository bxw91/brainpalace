---
last_validated: 2026-06-28
---

# Configuration Reference

This document provides a comprehensive reference for all BrainPalace configuration options, including environment variables, server settings, and per-project configuration.

## Table of Contents

- [Configuration Precedence](#configuration-precedence)
- [Server Configuration](#server-configuration)
- [Embedding Configuration](#embedding-configuration)
- [Chunking Configuration](#chunking-configuration)
- [Query Configuration](#query-configuration)
- [GraphRAG Configuration](#graphrag-configuration)
- [Multi-Instance Configuration](#multi-instance-configuration)
- [Storage Configuration](#storage-configuration)
- [Strict Mode](#strict-mode)
- [Job Queue Configuration](#job-queue-configuration)
- [Embedding Cache Configuration](#embedding-cache-configuration)
- [Reranking Configuration](#reranking-configuration)
- [Time-Decay Ranking](#time-decay-ranking)
- [Cross-Session Linking](#cross-session-linking)
- [Session, Git & LSP Sources](#session-git--lsp-sources)
- [Per-Project Configuration](#per-project-configuration)
- [Example Configurations](#example-configurations)

---

## Configuration Precedence

Settings are resolved in this order (first match wins):

1. **Command-line flags**: `brainpalace start --port 8080`
2. **Environment variables**: `export API_PORT=8080`
3. **Project config**: `.brainpalace/config.yaml`
4. **Global config**: `~/.config/brainpalace/config.yaml` (XDG, preferred; legacy `~/.brainpalace/config.yaml` is deprecated and logs a warning)
5. **Built-in defaults**: Defined in `settings.py`

> **Note:** The legacy `.brainpalace/config.json` is retired. The runtime bind
> (`bind_host`, `port_range_start`, `port_range_end`, `auto_port`) now lives in the
> `config.yaml` `bind:` section, and `exclude_patterns` in the `indexing:` section —
> both editable in the dashboard and `brainpalace init`, inherited project→global like
> every other key. The resolved port stays in `.brainpalace/runtime.json` (written by a
> running server). (`chunk_size`/`chunk_overlap` are advanced per-run flags on
> `brainpalace index`, not config keys — the built-in 512/50 suit nearly all corpora.)

### Global vs project editor — per-field scope

`brainpalace init --global` and the dashboard **Global Config tab** render the same
per-project registry fields as the project editor. The `init --global` CLI review
grid additionally omits fields whose `scope` is `"project"` only — for example
`session_indexing.archive.dir` (a project-relative path that makes no sense in a
global default); the dashboard tab does not apply this scope filter. When editing
the project layer, each
field whose effective value comes from the global config (rather than a project
override) is annotated **"inherited from global"** in the review grid.

An interactive `brainpalace init` opens **directly on this review grid** — values
resolved from `global < code` plus the detected provider — rather than walking a
linear sequence of consent questions. The grid **expands on ON**: each division is
a single line — `N. Label : field = value | field = value | …` — that lists
**every** visible field of an ON (its enable/mode gate active) or pure-config
division — secrets included, shown in full (the terminal is trusted) — and
collapses a toggleable OFF division to just its gate value. Empty fields
(blank/None, `{}`, `[]`) are **omitted** from the overview, and a field that
depends on a selector is shown only when that selector is active — e.g.
`storage.postgres` appears only while `storage.backend = postgres`, never under
`chroma` (the same `visible_when` rule the dashboard uses, single-sourced from
`config_fields.FIELD_VISIBLE_WHEN`). Booleans render `on`/`off`. Section
descriptions are shown **only when you drill in to edit**, not in the overview. Edit by division number or
`[A]ll`; drilling a division edits **all** its fields, asking the enable/mode gate
first and skipping a sub-block when its gate is OFF. `[C]ontinue` accepts;
billable/secret consent fields (embed-sessions, git-history, graphrag-extraction)
prompt with their warning only when you edit them, and opt-in billable fields stay
**OFF** on a plain accept. Section names and descriptions are single-sourced with
the web dashboard (the CLI registry `config_fields.GROUP_ORDER` /
`GROUP_DESCRIPTIONS`).

`dashboard.*` (autostart, port, poll interval, etc.) is a **separate fleet-wide
control-plane surface** — edited via the dashboard **Settings tab** or the
`init --global` dashboard step, NOT through the per-project config registry. It does
not appear in the Config or Global Config tabs.

---

## Server Configuration

### API Host and Port

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `127.0.0.1` | IP address to bind to |
| `API_PORT` | `8000` | Port number (0 = auto-assign) |
| `DEBUG` | `false` | Enable debug mode with auto-reload |

**Examples**:

```bash
# Bind to all interfaces (accessible from network)
export API_HOST="0.0.0.0"

# Use a specific port
export API_PORT="8080"

# Enable debug mode
export DEBUG="true"
```

**CLI Override**:

```bash
brainpalace start --host 0.0.0.0 --port 8080
```

### Server Modes

| Mode | Description |
|------|-------------|
| `project` | Per-project isolated server (default) |
| `shared` | Single server for multiple projects (future) |

```bash
export BRAINPALACE_MODE="project"
```

---

## Embedding Configuration

### OpenAI Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model name |
| `EMBEDDING_DIMENSIONS` | `3072` | Vector dimensions |
| `EMBEDDING_BATCH_SIZE` | `100` | Chunks per API call |

**Examples**:

```bash
# Required: OpenAI API key
export OPENAI_API_KEY="sk-proj-..."

# Use smaller model for cost savings
export EMBEDDING_MODEL="text-embedding-3-small"
export EMBEDDING_DIMENSIONS="1536"
```

### Anthropic API (Summarization)

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (optional) | Anthropic API key |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Claude model for summaries |

**Examples**:

```bash
# Optional: Enable LLM summaries and GraphRAG extraction
export ANTHROPIC_API_KEY="sk-ant-..."
export CLAUDE_MODEL="claude-haiku-4-5-20251001"
```

---

## Chunking Configuration

### Text Document Chunking

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `DEFAULT_CHUNK_SIZE` | `512` | 128-2048 | Target chunk size in tokens |
| `DEFAULT_CHUNK_OVERLAP` | `50` | 0-200 | Overlap between chunks |
| `MAX_CHUNK_SIZE` | `2048` | - | Maximum allowed chunk size |
| `MIN_CHUNK_SIZE` | `128` | - | Minimum allowed chunk size |

**Examples**:

```bash
# Larger chunks for detailed documents
export DEFAULT_CHUNK_SIZE="800"
export DEFAULT_CHUNK_OVERLAP="100"
```

**CLI Override**:

```bash
brainpalace index /path --chunk-size 800 --overlap 100
```

### Code Chunking

Code chunking uses different defaults optimized for source code:

| Setting | Default | Description |
|---------|---------|-------------|
| `chunk_lines` | `40` | Target lines per chunk |
| `chunk_lines_overlap` | `15` | Line overlap |
| `max_chars` | `1500` | Maximum characters |

These are set in the `CodeChunker` class and can be customized programmatically.

---

## Query Configuration

### Default Query Settings

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `DEFAULT_TOP_K` | `5` | 1-50 | Results to return |
| `MAX_TOP_K` | `50` | - | Maximum allowed top_k |
| `DEFAULT_SIMILARITY_THRESHOLD` | `0.7` | 0.0-1.0 | Minimum similarity |

**Examples**:

```bash
# Return more results by default
export DEFAULT_TOP_K="10"

# Lower threshold for broader matches
export DEFAULT_SIMILARITY_THRESHOLD="0.5"
```

**CLI Override**:

```bash
brainpalace query "search term" --top-k 10 --threshold 0.5
```

### Query Modes

| Mode | Alpha | Description |
|------|-------|-------------|
| `bm25` | N/A | Keyword-only search |
| `vector` | N/A | Semantic-only search |
| `hybrid` | `0.5` | BM25 + Vector fusion |
| `graph` | N/A | Graph traversal |
| `multi` | N/A | All three with RRF |

**Alpha Parameter** (hybrid mode only):
- `1.0`: Pure vector search
- `0.5`: Balanced (default)
- `0.0`: Pure BM25 search

---

## GraphRAG Configuration

### Enable/Disable

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_GRAPH_INDEX` | `true` | Master switch for GraphRAG (brainpalace init writes graphrag.enabled: true) |

**Example**:

```bash
# Enable GraphRAG
export ENABLE_GRAPH_INDEX="true"
```

### Graph Storage

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `GRAPH_STORE_TYPE` | `sqlite` | `simple` \| `sqlite` | Graph backend. `sqlite`: persistent, incremental, temporal-validity — default for all new projects. `simple`: in-memory + JSON, opt-in lightweight mode (temporal validity unavailable). Unknown values downgrade to `simple`. See [GRAPHRAG_GUIDE](GRAPHRAG_GUIDE.md#storage-backends). |
| `GRAPH_INDEX_PATH` | `./graph_index` | Path | Storage location |

**Examples**:

```bash
# Persistent SQLite store — incremental writes + temporal validity (default).
# Migrates an existing simple JSON graph on first use.
export GRAPH_STORE_TYPE="sqlite"

# In-memory store, JSON-persisted (opt-in lightweight mode; temporal validity unavailable).
export GRAPH_STORE_TYPE="simple"
```

### Entity Extraction

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPH_USE_CODE_METADATA` | `true` | Extract from AST metadata |
| `EXTRACTION_MODE` | `off` | Doc-graph + session extraction engine: `off` \| `subagent` (free) \| `auto` \| `provider` (BILLABLE) |
| `GRAPH_EXTRACTION_MODEL` | `claude-haiku-4-5` | LLM model for extraction |
| `GRAPH_MAX_TRIPLETS_PER_CHUNK` | `10` | Limit per chunk |

**Examples**:

```bash
# Code-only extraction (no LLM costs)
export GRAPH_USE_CODE_METADATA="true"
export GRAPH_USE_LLM_EXTRACTION="false"

# Full extraction with fast model
export GRAPH_USE_LLM_EXTRACTION="true"
export GRAPH_EXTRACTION_MODEL="claude-haiku-4-5"
```

### Graph Query

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `GRAPH_TRAVERSAL_DEPTH` | `2` | 1-4 | Hops to traverse |
| `GRAPH_RRF_K` | `60` | 20-100 | RRF constant |

**Examples**:

```bash
# Deeper traversal for complex relationships
export GRAPH_TRAVERSAL_DEPTH="3"

# Adjust RRF fusion (lower = more weight on top ranks)
export GRAPH_RRF_K="40"
```

---

## Multi-Instance Configuration

### State Directory

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINPALACE_STATE_DIR` | `None` | Override state directory location |
| `BRAINPALACE_MODE` | `project` | Instance mode: `project` or `shared` |

> **Legacy aliases:** `DOC_SERVE_STATE_DIR` is still read by `provider_config.py` as a fallback if `BRAINPALACE_STATE_DIR` is not set.

**Examples**:

```bash
# Explicit state directory
export BRAINPALACE_STATE_DIR="/path/to/.brainpalace"

# Project mode (default)
export BRAINPALACE_MODE="project"
```

### CLI Options

```bash
# Start with explicit state directory
brainpalace start --state-dir /path/to/.brainpalace

# Start with project directory (auto-resolves state)
brainpalace start --project-dir /path/to/project
```

---

## Query Cache Configuration

BrainPalace caches query results in memory to avoid redundant storage lookups
for repeated identical queries.  The cache is invalidated automatically whenever
a reindex job completes, ensuring freshness after every index update.

### Query Cache

| Variable | Default | Description |
|----------|---------|-------------|
| `QUERY_CACHE_TTL` | `3600` | Time-to-live for cached query results in seconds (default 1 hour). Set to a high value for mostly-static indexes, lower for frequently-updated ones. |
| `QUERY_CACHE_MAX_SIZE` | `256` | Maximum number of query results to cache. When full, least-recently-used entries are evicted by TTLCache. |

Notes:
- Query cache is in-memory only (no disk persistence). Cache is empty after server restart.
- `graph` and `multi` query modes are never cached (non-deterministic LLM extraction).
- Cache is automatically invalidated on every successful reindex job completion.
- Cache statistics are visible in the `/health/status` response under the `query_cache` key.

```bash
# Example: longer TTL for a static documentation server
QUERY_CACHE_TTL=3600
QUERY_CACHE_MAX_SIZE=512
```

---

## Strict Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINPALACE_STRICT_MODE` | `false` | Fail on critical validation errors instead of logging warnings |

When enabled, the server will raise errors for validation issues that would otherwise be logged as warnings (e.g., invalid chunk sizes, missing required metadata).

```bash
# Enable strict validation
export BRAINPALACE_STRICT_MODE="true"
```

---

## Tokenizer Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ALLOW_SPECIAL_TOKENS_IN_TEXT` | `true` | When `true`, tiktoken token counting passes `disallowed_special=()` so text containing literal special-token strings like `<\|endoftext\|>` (common in LLM / inference docs) does not crash indexing. Set `false` to restore the historical strict behavior that raises on such tokens. |

```bash
# Restore strict tokenizer behavior (raise on special-token literals)
export ALLOW_SPECIAL_TOKENS_IN_TEXT="false"
```

---

## Job Queue Configuration

Controls the background job queue used for indexing operations.

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINPALACE_MAX_QUEUE` | `100` | Maximum number of pending jobs in the queue |
| `BRAINPALACE_JOB_TIMEOUT` | `7200` | Job timeout in seconds (default: 2 hours) |
| `BRAINPALACE_MAX_RETRIES` | `3` | Maximum retry attempts for failed jobs |
| `BRAINPALACE_CHECKPOINT_INTERVAL` | `50` | Save progress checkpoint every N files |
| `BRAINPALACE_WATCH_DEBOUNCE_SECONDS` | `30` | File watcher debounce delay in seconds |

**Examples**:

```bash
# Increase queue size for large projects
export BRAINPALACE_MAX_QUEUE="500"

# Longer timeout for very large codebases
export BRAINPALACE_JOB_TIMEOUT="14400"

# More frequent checkpoints
export BRAINPALACE_CHECKPOINT_INTERVAL="25"

# Shorter debounce for faster file-watch response
export BRAINPALACE_WATCH_DEBOUNCE_SECONDS="10"
```

---

## Embedding Cache Configuration

Controls the two-tier (memory + disk) embedding cache that avoids redundant OpenAI API calls for previously-seen content.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_CACHE_MAX_DISK_MB` | `500` | Maximum disk cache size in megabytes |
| `EMBEDDING_CACHE_MAX_MEM_ENTRIES` | `10000` | Maximum in-memory LRU cache entries |
| `EMBEDDING_CACHE_PERSIST_STATS` | `false` | Persist hit/miss statistics across server restarts |

**Examples**:

```bash
# Larger disk cache for big repos
export EMBEDDING_CACHE_MAX_DISK_MB="2000"

# Larger in-memory cache
export EMBEDDING_CACHE_MAX_MEM_ENTRIES="5000"

# Persist cache statistics for monitoring
export EMBEDDING_CACHE_PERSIST_STATS="true"
```

---

## Reranking Configuration

Controls the two-stage reranking pipeline that improves search relevance by using a cross-encoder model to rescore initial retrieval results. **Reranking is OFF by default** — the cross-encoder is a *local* model (no API/token cost) but needs the heavy `reranker-local` extra (~2.8 GB PyTorch) and adds query latency. It is gated by the `reranker.enabled` key in `config.yaml` (default `false`), which `brainpalace init` writes; the `ENABLE_RERANKING` env var **overrides** the config when set. Enable per-project with `reranker.enabled: true`, at init with `--reranking` (installs the extra), or globally with `ENABLE_RERANKING=true`.

```yaml
# config.yaml — per-project switch (default false)
reranker:
  enabled: false
  provider: sentence-transformers   # or "ollama"
```

| Variable | Default | Description |
|----------|---------|-------------|
| `reranker.enabled` (config) | `false` | Per-project master switch (written by `brainpalace init`) |
| `ENABLE_RERANKING` (env) | (overrides config) | Force reranking on/off regardless of config |
| `RERANKER_PROVIDER` | `sentence-transformers` | Reranker backend (`sentence-transformers` or `ollama`) |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model name |
| `RERANKER_TOP_K_MULTIPLIER` | `10` | Stage 1 retrieves `top_k * multiplier` candidates |
| `RERANKER_MAX_CANDIDATES` | `100` | Maximum Stage 1 candidates (caps the multiplier) |

**Examples**:

```bash
# Enable reranking
export ENABLE_RERANKING="true"

# Use a different cross-encoder model
export RERANKER_MODEL="cross-encoder/ms-marco-TinyBERT-L-2-v2"

# Retrieve more candidates for reranking
export RERANKER_TOP_K_MULTIPLIER="20"
export RERANKER_MAX_CANDIDATES="200"
```

---

## Time-Decay Ranking

Ranks **newer** chunks higher (sessions, git commits, decisions, recently-edited
code) by multiplying each result's score by an exponential age factor
`0.5 ** (age_days / half_life)` before ranking. On by default with a gentle
90-day half-life.

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS` | `90` | Half-life in days. A chunk this old gets ½ weight, twice as old ¼, etc. **`0` disables** decay globally. |

Per-query override: `brainpalace query "..." --no-time-decay` (or
`time_decay: false` in the API request body). A chunk's age comes from its
`created_at` metadata; chunks without it get no penalty. Decayed scores are
cached (drift is negligible over the cache TTL vs the day-scale half-life) and
the `time_decay` flag is part of the cache key. With reranking on, decay shapes
the Stage-1 candidate pool and the reranker sets final order.

```bash
# Sharper recency bias (30-day half-life)
export BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS="30"

# Disable decay entirely
export BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS="0"
```

---

## Cross-Session Linking

Keeps the session knowledge graph self-consistent over time (Phase 140). Runs
during `/sessions/extract`; the supersession/penalty parts have **full effect
only on the `sqlite` graph backend** (temporal ops no-op on `simple`). See
[GRAPH_TAXONOMY](GRAPH_TAXONOMY.md#cross-session-linking-phase-140).

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINPALACE_PROMOTE_DECISIONS` | `true` | Promote durable, rationale-backed session decisions into the curated-memory namespace (030). `false` disables promotion. |
| `BRAINPALACE_STALE_DECISION_PENALTY` | `0.5` | Ranking multiplier for `session_decision` results whose decision has been superseded. `1.0` = off; lower = stronger down-rank. |

File-like triplet entities are also canonicalised to project-root-relative paths
so the graph keeps one node per real file (no per-query setting).

---

## Compute Configuration

Controls the compute query mode and the typed numeric records store. Mirrors
the `graphrag:` config pattern — the `compute:` YAML section overrides defaults,
and env vars win over YAML when both are set.

### Environment variables

The `compute` query mode has **no switches** — like `bm25`/`vector` it is always
selectable and simply returns empty when no records exist. (Unlike `graph`,
which is gated by `ENABLE_GRAPH_INDEX`.) Records are extracted automatically
whenever session extraction runs (gated by `extraction.mode`); there is
no separate record-extraction toggle. The only compute knob is the confidence
floor below.

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPUTE_MIN_CONFIDENCE` | `0.7` | Confidence floor for records entering aggregates (0.0–1.0). Records below this threshold are stored but excluded from compute results by default. With the default 0.7, only HIGH-confidence records (`1.0`) are summed. |

### `compute:` config.yaml section

```yaml
compute:
  min_confidence: 0.7       # null = inherit (COMPUTE_MIN_CONFIDENCE)
```

An absent key (or `null`) inherits from the env var or the code default; env
vars win over YAML when both are set.

**Examples**:

```bash
# Lower the floor to include PROVISIONAL records (confidence >= 0.6)
export COMPUTE_MIN_CONFIDENCE="0.6"
```

See [COMPUTE.md](COMPUTE.md) for the full guide including confidence tiers,
record population, and the `--json` response contract.

---

## Session, Git & LSP Sources

These opt-in subsystems have dedicated guides; the key switches:

| Variable / config | Default | Description |
|---|---|---|
| `session_indexing:` block / `SESSION_INDEXING_ENABLED` | off | Index runtime JSONL transcripts as `session_turn` chunks. See [SESSION_INDEXING](SESSION_INDEXING.md). |
| `BRAINPALACE_PROMOTE_DECISIONS` | `true` | Promote durable session decisions into curated memory (Phase 140). |
| `git_indexing:` block / `GIT_INDEXING_ENABLED` | off | Index git commits (message + diff stat) as `git_commit` chunks. See [GIT_HISTORY](GIT_HISTORY.md). |
| `git_indexing.path_filter` | (empty) | List of repo-relative paths; when set, only commits that touched these paths are indexed (`git log -- <paths>`). Empty = all commits. Use in a mono-repo where one `.git/` serves many projects. |
| `BRAINPALACE_LSP_LANGUAGES` | `""` (inert) | Comma-separated language allow-list for the opt-in LSP cross-reference graph (requires the server binary). See [LSP_INTEGRATION](LSP_INTEGRATION.md). |

---

## Storage Configuration

### Storage Backend Selection

BrainPalace supports multiple storage backends:

- `chroma` (default)
- `postgres`

Selection order (first match wins):

1. `BRAINPALACE_STORAGE_BACKEND` environment variable
2. `storage.backend` in `config.yaml`
3. Built-in default (`chroma`)

**Example** (`config.yaml`):

```yaml
storage:
  backend: "postgres"  # or "chroma"
```

**Environment override**:

```bash
export BRAINPALACE_STORAGE_BACKEND="postgres"
```

### PostgreSQL Backend (pgvector)

When `storage.backend` is `postgres`, configure connection and pool settings
under `storage.postgres`:

```yaml
storage:
  backend: "postgres"
  postgres:
    host: "localhost"
    port: 5432
    database: "brainpalace"
    user: "brainpalace"
    password: "brainpalace_dev"
    pool_size: 10
    pool_max_overflow: 10
    pool_timeout: 30
    language: "english"
    hnsw_m: 16
    hnsw_ef_construction: 64
    debug: false
```

**PostgreSQL connection and pool keys:**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `"localhost"` | Database host |
| `port` | int | `5432` | Database port |
| `database` | string | `"brainpalace"` | Database name |
| `user` | string | `"brainpalace"` | Database user |
| `password` | string | `""` | Database password |
| `pool_size` | int | `10` | Connections to keep in the pool |
| `pool_max_overflow` | int | `10` | Extra connections above `pool_size` |
| `pool_timeout` | int | `30` | Seconds to wait for a pool connection before timeout |
| `language` | string | `"english"` | Full-text search language |
| `hnsw_m` | int | `16` | HNSW index M parameter |
| `hnsw_ef_construction` | int | `64` | HNSW construction parameter |
| `debug` | bool | `false` | Enable SQLAlchemy debug logging |

**Connection string override**:

`DATABASE_URL` overrides the host/user/password/database/port connection
string, but pool settings and HNSW tuning remain in YAML.

```bash
export DATABASE_URL="postgresql+asyncpg://brainpalace:brainpalace_dev@localhost:5432/brainpalace"
```

### ChromaDB Vector Store

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB storage location |
| `COLLECTION_NAME` | `brainpalace_collection` | Collection name |

**Examples**:

```bash
# Custom storage location
export CHROMA_PERSIST_DIR="/data/brainpalace/vectors"
```

### BM25 Index

| Variable | Default | Description |
|----------|---------|-------------|
| `BM25_INDEX_PATH` | `./bm25_index` | BM25 index storage |

**Examples**:

```bash
# Custom BM25 storage
export BM25_INDEX_PATH="/data/brainpalace/bm25"
```

---

## Per-Project Configuration

### config.yaml — `bind:` and `indexing:` sections

The runtime bind and chunking knobs live in `.brainpalace/config.yaml` (the legacy
`config.json` is retired). Both sections are model-backed, so they render and are
editable in the dashboard Config tab and the `brainpalace init` review grid, and are
inherited project→global like every other key:

```yaml
bind:
  bind_host: "127.0.0.1"
  port_range_start: 8000
  port_range_end: 8100
  auto_port: true
indexing:
  exclude_patterns:
    - "**/node_modules/**"
    - "**/__pycache__/**"
    - "**/.venv/**"
    - "**/venv/**"
    - "**/.git/**"
    - "**/dist/**"
    - "**/build/**"
    - "**/target/**"
```

### Configuration Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `bind.bind_host` | string | `"127.0.0.1"` | Server bind address (loopback by default — see security note) |
| `bind.port_range_start` | integer | `8000` | Start of port range for auto-port |
| `bind.port_range_end` | integer | `8100` | End of port range for auto-port |
| `bind.auto_port` | boolean | `true` | Automatically find available port |
| `indexing.exclude_patterns` | array | (see example) | Glob patterns to exclude from indexing |

> **Chunk size/overlap** are advanced per-run flags on `brainpalace index`
> (`--chunk-size`, `--chunk-overlap`; defaults 512 / 50), not config keys — the
> built-in defaults suit nearly all corpora.

> ⚠️ **Security — the API is unauthenticated.** BrainPalace binds `127.0.0.1`
> (loopback) by default and assumes a single-user, localhost trust model: the
> write endpoints (e.g. the graph-extraction **submit** path, which mutates the
> knowledge graph and can spend embedding budget) have **no auth**. Setting
> `bind_host` / `--host` to a non-loopback address (`0.0.0.0`) exposes every
> endpoint to the network — only do so on a trusted network or behind a reverse
> proxy that adds authentication.

---

## Example Configurations

### Development Setup

Minimal configuration for local development:

```bash
# .env
OPENAI_API_KEY=sk-proj-...
DEBUG=true
DEFAULT_TOP_K=10
DEFAULT_SIMILARITY_THRESHOLD=0.5
```

### Production Setup

Full configuration for production deployment:

```bash
# .env
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# Server
API_HOST=127.0.0.1
API_PORT=8000
DEBUG=false

# Embedding
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072
EMBEDDING_BATCH_SIZE=100

# Query defaults
DEFAULT_TOP_K=5
DEFAULT_SIMILARITY_THRESHOLD=0.7

# Storage
CHROMA_PERSIST_DIR=/data/brainpalace/vectors
BM25_INDEX_PATH=/data/brainpalace/bm25

# GraphRAG (optional)
ENABLE_GRAPH_INDEX=true
GRAPH_STORE_TYPE=sqlite
GRAPH_INDEX_PATH=/data/brainpalace/graph
GRAPH_USE_CODE_METADATA=true
GRAPH_USE_LLM_EXTRACTION=true
GRAPH_EXTRACTION_MODEL=claude-haiku-4-5
GRAPH_TRAVERSAL_DEPTH=2

# Embedding cache
EMBEDDING_CACHE_MAX_DISK_MB=2000
EMBEDDING_CACHE_MAX_MEM_ENTRIES=5000

# Job queue
BRAINPALACE_MAX_QUEUE=500
BRAINPALACE_JOB_TIMEOUT=7200
BRAINPALACE_CHECKPOINT_INTERVAL=50

# Reranking (optional)
ENABLE_RERANKING=true
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

### Code-Heavy Repository

Configuration optimized for source code:

```bash
# .env
OPENAI_API_KEY=sk-proj-...

# Larger chunks for code
DEFAULT_CHUNK_SIZE=800
DEFAULT_CHUNK_OVERLAP=100

# GraphRAG for code relationships
ENABLE_GRAPH_INDEX=true
GRAPH_USE_CODE_METADATA=true
GRAPH_USE_LLM_EXTRACTION=false  # Code metadata is sufficient
```

Project config (`.brainpalace/config.yaml`):

```yaml
bind:
  bind_host: "127.0.0.1"
  port_range_start: 8000
  port_range_end: 8100
  auto_port: true
indexing:
  exclude_patterns:
    - "**/node_modules/**"
    - "**/__pycache__/**"
    - "**/dist/**"
    - "**/build/**"
```

> Larger chunks for code? Use `brainpalace index --chunk-size 800 --chunk-overlap 100`
> (or the `DEFAULT_CHUNK_SIZE`/`DEFAULT_CHUNK_OVERLAP` env vars) — chunk sizing is a
> per-run flag, not a config key.

### Documentation-Only Setup

Configuration for pure documentation search:

```bash
# .env
OPENAI_API_KEY=sk-proj-...

# Smaller chunks for precise documentation
DEFAULT_CHUNK_SIZE=400
DEFAULT_CHUNK_OVERLAP=50

# No GraphRAG needed
ENABLE_GRAPH_INDEX=false
```

Project config:

```yaml
bind:
  bind_host: "127.0.0.1"
  port_range_start: 8000
  port_range_end: 8100
  auto_port: true
indexing:
  exclude_patterns:
    - "**/node_modules/**"
    - "**/__pycache__/**"
    - "**/.git/**"
```

### Cost-Optimized Setup

Minimize API costs:

```bash
# .env
OPENAI_API_KEY=sk-proj-...

# Use smaller embedding model
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

# Disable LLM extraction
GRAPH_USE_LLM_EXTRACTION=false
```

---

## Environment File Locations

BrainPalace searches for `.env` files in this order:

1. Current working directory: `./.env`
2. Project root: `../.env`
3. Server package directory: `brainpalace-server/.env`

**Best Practice**: Place `.env` in your project root and add to `.gitignore`.

---

## Validation

### Check Current Configuration

```bash
# View server status (includes some config)
brainpalace status

# View all environment variables
env | grep -E "(OPENAI|ANTHROPIC|EMBEDDING|GRAPH|CHUNK|API)"
```

### Test Configuration

```bash
# Start server and check health
brainpalace start
curl http://127.0.0.1:8000/health

# Index test documents
brainpalace index ./docs

# Test query
brainpalace query "test" --mode hybrid
```

---

## Next Steps

- [API Reference](API_REFERENCE.md) - REST API documentation
- [Deployment Guide](DEPLOYMENT.md) - Production deployment
- [Architecture Overview](ARCHITECTURE.md) - System design
