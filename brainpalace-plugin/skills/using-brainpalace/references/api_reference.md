---
last_validated: 2026-06-20
---

# BrainPalace API Reference

## Base URL

Discover from runtime file (multi-instance mode):
```bash
cat .brainpalace/runtime.json | jq -r '.base_url'
# Example: http://127.0.0.1:54321
```

Default (single instance): `http://127.0.0.1:8000`

Override via environment: `BRAINPALACE_URL`

---

## Health Endpoints

### GET /health

Check server health status.

**Response:**

```json
{
  "status": "healthy | indexing | degraded | unhealthy",
  "message": "Server is running and ready for queries",
  "version": "1.0.0",
  "timestamp": "2024-12-15T10:00:00Z"
}
```

**Status Values:**
- `healthy` - Server ready for queries
- `indexing` - Indexing in progress, queries may fail
- `degraded` - Server up but some services unavailable
- `unhealthy` - Server not operational

---

### GET /health/status

Get detailed indexing status.

**Response:**

```json
{
  "total_documents": 100,
  "total_chunks": 500,
  "indexing_in_progress": false,
  "current_job_id": null,
  "progress_percent": 0.0,
  "last_indexed_at": "2024-12-15T10:00:00Z",
  "indexed_folders": ["/docs/kubernetes", "/docs/python"],
  "graph_index": {
    "enabled": true,
    "entity_count": 450,
    "relationship_count": 1200,
    "store_type": "simple"
  }
}
```

**Graph Index Fields** (when `ENABLE_GRAPH_INDEX=true`):
- `enabled` - Whether graph indexing is active
- `entity_count` - Number of extracted entities (functions, classes, modules)
- `relationship_count` - Number of relationships (calls, imports, inherits)
- `store_type` - Graph store backend (`simple`; `unavailable` for non-chroma backends). A configured `sqlite` value is auto-downgraded to `simple`.

---

## Query Endpoints

### POST /query

Execute a semantic search on indexed documents.

**Request Body:**

```json
{
  "query": "how to configure pod networking",
  "top_k": 5,
  "similarity_threshold": 0.3,
  "mode": "hybrid",
  "alpha": 0.5
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query text |
| `top_k` | integer | No | 5 | Number of results (1-50) |
| `similarity_threshold` | float | No | 0.3 | Minimum similarity (0.0-1.0) |
| `mode` | string | No | hybrid | Retrieval mode (`vector`, `bm25`, `hybrid`, `graph`, `multi`) |
| `alpha` | float | No | 0.5 | Hybrid weight (1.0=vector, 0.0=bm25) |
| `use_memory` | boolean | No | true | Boost curated memories into results (vector/hybrid/multi; ignored for bm25) |
| `time_decay` | boolean | No | true | Rank newer chunks higher (set false to disable for this query) |
| `rerank` | boolean\|null | No | null | Per-request reranking override (true=force, false=off, null=follow `ENABLE_RERANKING`) |
| `source_types` | string[] | No | - | Filter by source type: `doc`, `code`, `test` |
| `languages` | string[] | No | - | Filter by programming language(s) for code files |
| `file_paths` | string[] | No | - | Filter by file paths (wildcards supported, e.g. `src/**/*.py`) |
| `language` | string | No | - | BM25 query language override (ISO 639-1); defaults to project `bm25.language` |
| `entity_types` | string[] | No | - | **Graph filter** — restrict to entity types (e.g. `["Class","Function"]`). Graph/multi modes only |
| `relationship_types` | string[] | No | - | **Graph filter** — restrict to relationship types (e.g. `["calls","extends"]`). Graph/multi modes only |

**Graph queries:**
- **Per-request graph control** is via `entity_types` / `relationship_types` (above) —
  filter which entities and relationships the graph walk returns.
- **Traversal depth is NOT a request parameter** — it is fixed server-side by the
  `GRAPH_TRAVERSAL_DEPTH` config/env var (default 2, applied to every graph/multi
  query). There is no per-query override.
- Relationships are **always** returned in graph/multi modes (see `related_entities` /
  `relationship_path` in the response) — there is no boolean to toggle them.

**Response:**

```json
{
  "results": [
    {
      "text": "Pod networking in Kubernetes allows...",
      "source": "docs/kubernetes/networking.md",
      "score": 0.92,
      "vector_score": 0.92,
      "bm25_score": 0.85,
      "graph_score": 0.78,
      "chunk_id": "chunk_abc123",
      "metadata": {
        "page": 1,
        "section": "Pod Networking"
      },
      "related_entities": ["configure_network", "kubernetes.networking"],
      "relationship_path": ["setup_pod", "CALLS", "configure_network"]
    }
  ],
  "query_time_ms": 45.2,
  "total_results": 1
}
```

**Response Fields:**
- `graph_score` - Graph relevance score. Always present in the schema; `null` for non-graph modes.
- `related_entities` - List of related entity names (string list), populated in graph/multi modes.
- `relationship_path` - Ordered relationship path (string list), populated in graph/multi modes.

**Error Responses:**

| Status | Description |
|--------|-------------|
| 400 | Query is empty or invalid |
| 503 | Index not ready (indexing in progress) |
| 500 | Internal server error |

---

### GET /query/count

Get the total number of indexed document chunks.

**Response:**

```json
{
  "total_chunks": 500,
  "ready": true
}
```

---

## Index Endpoints

### POST /index

Start indexing documents from a folder. The system uses stable IDs based on file paths and chunk indices, meaning re-indexing the same folder will update existing records (upsert) rather than creating duplicates.

**Request Body:**

```json
{
  "folder_path": "/path/to/documents",
  "recursive": true,
  "chunk_size": 512,
  "chunk_overlap": 50
}
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `folder_path` | string | Yes | - | Absolute or relative path to documents |
| `recursive` | boolean | No | true | Include subdirectories |
| `chunk_size` | integer | No | 512 | Target tokens per chunk |
| `chunk_overlap` | integer | No | 50 | Overlap between chunks |

---

### POST /index/add

Add documents incrementally without clearing existing index.

**Request Body:**

```json
{
  "folder_path": "/path/to/more/documents",
  "recursive": true
}
```

---

### DELETE /index

Clear all indexed documents.

**Response:**

```json
{
  "job_id": "reset",
  "status": "completed",
  "message": "Index has been reset successfully"
}
```

---

## Cache Endpoints

### GET /index/cache

Retrieve embedding cache statistics for the current session and persisted disk cache.

**Response:**

```json
{
  "hits": 5432,
  "misses": 800,
  "hit_rate": 0.8712,
  "mem_entries": 500,
  "entry_count": 1234,
  "size_bytes": 15531008
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `hits` | integer | Total successful cache lookups this session |
| `misses` | integer | Total cache misses (embedding computed via API) this session |
| `hit_rate` | float | Fraction of lookups served from cache (0.0–1.0). Resets on server restart. |
| `mem_entries` | integer | Embeddings currently held in the in-memory LRU tier |
| `entry_count` | integer | Total embeddings persisted in the SQLite disk cache |
| `size_bytes` | integer | Total bytes used by the disk cache database |

**Note:** Both `/index/cache` and `/index/cache/` are accepted (trailing-slash alias).
Use the no-trailing-slash form (`/index/cache`) to avoid 307 redirects.

**Error Responses:**

| Status | Description |
|--------|-------------|
| 503 | Cache not initialized (server starting up or cache subsystem unavailable) |

---

### DELETE /index/cache

Clear all cached embeddings from the disk cache. The next reindex will recompute
embeddings via the configured embedding provider.

**Response:**

```json
{
  "count": 1234,
  "size_bytes": 15531008,
  "size_mb": 14.81
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Number of cached embeddings that were removed |
| `size_bytes` | integer | Bytes freed from the disk cache |
| `size_mb` | float | Megabytes freed (`size_bytes / 1024 / 1024`, unrounded) |

**Note:** Both `/index/cache` and `/index/cache/` are accepted (trailing-slash alias).

**Error Responses:**

| Status | Description |
|--------|-------------|
| 503 | Cache not initialized (server starting up or cache subsystem unavailable) |

---

## OpenAPI Documentation

Interactive API documentation available at:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

---

## CLI Commands Reference

The `brainpalace` CLI provides these commands:

```bash
# Server lifecycle
brainpalace init                      # Initialize project config
brainpalace start            # Start server with auto-port
brainpalace stop                      # Stop running server
brainpalace list                      # List all running instances

# Check server health and status
brainpalace status
brainpalace status --json

# Query documents
brainpalace query "search text"
brainpalace query "search text" --mode hybrid --top-k 10
brainpalace query "search text" --mode graph
brainpalace query "search text" --mode multi
brainpalace query "search text" --json

# Index documents
brainpalace index /path/to/docs
brainpalace index /path/to/docs --recursive

# Folder management
brainpalace folders add ./docs                          # Index a folder
brainpalace folders add ./src --include-code            # Index with code
brainpalace folders add ./src --watch auto              # Enable auto-reindex
brainpalace folders add ./src --watch auto --debounce 10  # Custom debounce
brainpalace folders list                                # Show all folders
brainpalace folders remove ./docs --yes                 # Remove folder

# Job queue
brainpalace jobs                      # List all jobs
brainpalace jobs --watch              # Watch queue live
brainpalace jobs JOB_ID               # Show job details
brainpalace jobs JOB_ID --cancel      # Cancel a job

# Clear index
brainpalace reset --yes

# Embedding cache
brainpalace cache status             # View cache metrics (human-readable)
brainpalace cache status --json      # View metrics as JSON
brainpalace cache clear              # Clear cache (prompts for confirmation)
brainpalace cache clear --yes        # Clear cache (skips confirmation)
```

**Folder Options (folders add):**
- `--include-code` - Index source code files alongside documents
- `--watch MODE` - Watch mode: `auto` (enable file watching) or `off` (default)
- `--debounce N` - Debounce interval in seconds for file watching (default: 30)

**Folders List Output:**

| Column | Description |
|--------|-------------|
| Folder Path | Canonical absolute path |
| Chunks | Number of indexed chunks |
| Last Indexed | Timestamp of last indexing run |
| Watch | Watch mode: `auto` or `off` |

**Jobs List Output:**

| Column | Description |
|--------|-------------|
| ID | Job identifier |
| Status | pending, running, done, failed, cancelled |
| Source | `manual` (user-triggered) or `auto` (watcher-triggered) |
| Folder | Folder being indexed |
| Progress | Completion percentage |

**Query Options:**
- `--mode MODE` - Search mode: bm25, vector, hybrid, graph, multi
- `--top-k N` - Number of results (default: 5)
- `--threshold F` - Minimum similarity (default: 0.3)
- `--alpha F` - Hybrid balance, 0=BM25, 1=Vector (default: 0.5)

**File Type Presets (v7.0+):**
```bash
brainpalace types list                          # Show available presets
brainpalace index ./src --include-type python   # Index with preset filter
brainpalace index ./src --include-type typescript
```

**Content Injection (v7.0+):**
```bash
brainpalace inject --script enrich.py ./docs    # Index with injection
```

**Configuration (v8.0+):**
```bash
brainpalace config show                         # Show current configuration
brainpalace config path                         # Show active config file path
brainpalace config wizard --global              # Reconfigure providers (writes global XDG config)
brainpalace config validate                     # Validate the active config
```

**Multi-Runtime Install (v9.0+):**
```bash
brainpalace install-agent --agent claude        # Install for Claude
brainpalace install-agent --agent opencode      # Install for OpenCode
brainpalace install-agent --agent gemini        # Install for Gemini
brainpalace install-agent --agent codex         # Install for Codex
brainpalace install-agent --agent skill-runtime --dir /path  # Generic
brainpalace install-agent --agent claude --dry-run  # Preview
brainpalace install-agent --agent claude --global  # Global install
brainpalace uninstall                           # Guided teardown
brainpalace uninstall --yes --json              # Global-only, non-interactive
```

**Global Options:**
- `--url URL` - Server URL (default: http://127.0.0.1:8000)
- `--json` - Output as JSON
- `--help` - Show help message

---

## File Watcher

Folders configured with `watch_mode: auto` are automatically re-indexed when files change. This eliminates the need to manually re-run indexing after edits.

**How it works:**
- After `brainpalace folders add ./src --watch auto`, the server monitors the folder for file changes
- Per-folder debounce collapses rapid changes (e.g., git checkout, IDE save-all) into a single reindex job
- Watcher-triggered jobs use incremental diff (`force=False`) for efficiency -- only changed files are re-processed
- Jobs created by the watcher show `source: auto` in the jobs list

**Excluded directories:**
The watcher ignores changes in: `.git/`, `node_modules/`, `__pycache__/`, `dist/`, `build/`, `.next/`, `.nuxt/`, `coverage/`, `htmlcov/`

**Configuration:**
- Default debounce: 30 seconds (configurable via `BRAINPALACE_WATCH_DEBOUNCE_SECONDS`)
- Per-folder override: `--debounce N` on `folders add`

**Examples:**
```bash
# Enable auto-reindex with default 30s debounce
brainpalace folders add ./src --watch auto --include-code

# Custom 10-second debounce for fast iteration
brainpalace folders add ./src --watch auto --debounce 10

# Disable watching for a folder
brainpalace folders add ./docs --watch off
```
