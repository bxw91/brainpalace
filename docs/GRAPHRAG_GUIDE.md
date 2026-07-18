---
last_validated: 2026-07-18
---

# GraphRAG Integration Guide

GraphRAG extends BrainPalace with knowledge graph capabilities, enabling relationship-aware retrieval that surfaces connections between entities, code dependencies, and conceptual relationships.

## Table of Contents

- [What is GraphRAG?](#what-is-graphrag)
- [Why GraphRAG Matters](#why-graphrag-matters)
- [Enabling GraphRAG](#enabling-graphrag)
- [Entity Extraction](#entity-extraction)
- [Query Modes](#query-modes)
- [Reciprocal Rank Fusion](#reciprocal-rank-fusion)
- [Structural Queries](#structural-queries)
- [Best Practices](#best-practices)
- [Performance Considerations](#performance-considerations)

---

## What is GraphRAG?

GraphRAG combines traditional RAG (Retrieval-Augmented Generation) with knowledge graph technology. Instead of treating documents as isolated chunks of text, GraphRAG:

1. **Extracts Entities**: Identifies named concepts, classes, functions, and other significant items
2. **Captures Relationships**: Records how entities relate to each other (imports, calls, extends, contains)
3. **Enables Graph Queries**: Answers questions about structure and relationships, not just content

### The Knowledge Graph Model

BrainPalace uses a **property graph** model with triplets:

```
Subject --[Predicate]--> Object

Examples:
  FastAPI --[uses]--> Pydantic
  UserController --[contains]--> authenticate_user
  auth_module --[imports]--> jwt
```

Each triplet includes:
- **Subject**: The source entity (e.g., "FastAPI")
- **Subject Type**: Classification (e.g., "Framework")
- **Predicate**: Relationship type (e.g., "uses")
- **Object**: The target entity (e.g., "Pydantic")
- **Object Type**: Classification (e.g., "Library")
- **Source Chunk ID**: Link back to the original document chunk

---

## Why GraphRAG Matters

### Limitations of Vector-Only Search

Vector search excels at semantic similarity but misses structural relationships:

| Query | Vector Search Result | GraphRAG Result |
|-------|---------------------|-----------------|
| "What calls authenticate_user?" | Documents mentioning authentication | Actual callers: LoginController.login, API.verify |
| "What does FastAPI depend on?" | FastAPI documentation | Dependencies: Pydantic, Starlette, Uvicorn |
| "Classes in the auth module" | Auth-related content | Actual classes: AuthService, TokenManager, User |

### When GraphRAG Shines

GraphRAG is most valuable for:

1. **Dependency Analysis**: "What modules import this library?"
2. **Architecture Exploration**: "What classes extend BaseService?"
3. **Impact Assessment**: "What would break if I change this function?"
4. **Onboarding**: "Show me how authentication flows through the system"

---

## Enabling GraphRAG

**New projects:** `brainpalace init` writes a default `.brainpalace/config.yaml` with
`graphrag.enabled: true` and `use_code_metadata: true` — code-only AST graph indexing
is on automatically for fresh projects with no additional setup. Run
`brainpalace config wizard` to opt into LangExtract doc-graph (LLM cost).

**Existing projects or custom configuration:** use environment variables or edit
`config.yaml` directly (see sections below).

### Configuration Precedence

```
environment variables  >  config.yaml graphrag: section  >  built-in defaults
```

Environment variables always win (12-factor). `config.yaml` overrides built-in defaults.
See `PROVIDER_CONFIGURATION.md` for the full provider field reference.

### Basic Configuration

```bash
# Enable graph indexing (required for existing/manual setup)
export ENABLE_GRAPH_INDEX=true

# Start server
brainpalace start --daemon
```

### Full Configuration

```bash
# Required
export ENABLE_GRAPH_INDEX=true

# Graph storage backend
export GRAPH_STORE_TYPE=simple  # "simple" (in-memory, JSON) or "sqlite" (persistent)
export GRAPH_INDEX_PATH=./graph_index  # Storage location

# Entity extraction settings
export GRAPH_USE_CODE_METADATA=true  # Extract from AST metadata (fast)
export GRAPH_EXTRACTION_MODEL=claude-haiku-4-5  # Model for LLM extraction
export GRAPH_MAX_TRIPLETS_PER_CHUNK=10  # Limit per chunk

# Query settings
export GRAPH_TRAVERSAL_DEPTH=2  # How many hops to traverse
export GRAPH_RRF_K=60  # Reciprocal Rank Fusion constant
```

### In .env File

```ini
# brainpalace-server/.env
ENABLE_GRAPH_INDEX=true
GRAPH_STORE_TYPE=simple
GRAPH_USE_CODE_METADATA=true
GRAPH_EXTRACTION_MODEL=claude-haiku-4-5
```

**LLM extraction has no env var.** It is selected solely by the `extraction.mode`
key in `config.yaml` (`off` | `subagent` | `auto` | `provider`) — see below.

### In config.yaml

Configure GraphRAG via `.brainpalace/config.yaml`. All 8 `graphrag:` fields are
supported and applied at server startup (Phase G). `brainpalace init` writes this file automatically
for new projects with sensible defaults.

```yaml
graphrag:
  enabled: true                                    # Master switch (default: true)
  store_type: "sqlite"                             # "sqlite" (default — persistent + temporal) or "simple" (in-memory, JSON)
  index_path: ".brainpalace/data/graph_index"      # Storage location (relative to project root)
  use_code_metadata: true                          # Extract entities from AST metadata (fast, free)
  extraction_model: "claude-haiku-4-5"             # Model used by the async extraction reconciler
  max_triplets_per_chunk: 10                       # Limit triplets extracted per chunk
  traversal_depth: 2                               # Graph traversal depth for queries
  rrf_k: 60                                        # Reciprocal Rank Fusion constant

# Doc-graph + session extraction engine (governs both consumers)
extraction:
  mode: "off"       # off (default, cost-safe) | subagent (free) | auto | provider (BILLABLE)
  grace_hours: 24   # auto mode: hours before paid provider drains a pending chunk
```

The full environment variable ↔ config.yaml mapping:

| Environment Variable | config.yaml Key | Default |
|---------------------|-----------------|---------|
| `ENABLE_GRAPH_INDEX` | `graphrag.enabled` | `true` (master switch; brainpalace init also writes graphrag.enabled: true) |
| `GRAPH_STORE_TYPE` | `graphrag.store_type` | `sqlite` |
| `GRAPH_INDEX_PATH` | `graphrag.index_path` | `.brainpalace/data/graph_index` |
| `GRAPH_USE_CODE_METADATA` | `graphrag.use_code_metadata` | `true` |
| `GRAPH_EXTRACTION_MODEL` | `graphrag.extraction_model` | `claude-haiku-4-5` |
| `GRAPH_MAX_TRIPLETS_PER_CHUNK` | `graphrag.max_triplets_per_chunk` | `10` |
| `GRAPH_TRAVERSAL_DEPTH` | `graphrag.traversal_depth` | `2` |
| `GRAPH_RRF_K` | `graphrag.rrf_k` | `60` |

The `extraction:` section is **config.yaml-only** — `extraction.mode` (default
`off`) and `extraction.grace_hours` (default `24`) have no environment-variable
equivalent.

**Note:** The `graph` query mode requires GraphRAG enabled with the ChromaDB backend and is not available with the PostgreSQL storage backend. The `multi` query mode gracefully adapts when GraphRAG or ChromaDB is unavailable — it automatically uses BM25 + vector search only, skipping the graph component without error.

---

## Entity Extraction

> **Implementation note:** Graph indexing stores and retrieves real triplets.
> `add_triplet` upserts via the property-graph API; entity and relationship counts
> derive from actual store data. GRAPH and MULTI query modes return real results.

BrainPalace uses two complementary extraction methods:

### 1. Code Metadata Extraction (Fast, Deterministic)

Extracts relationships from AST metadata already collected during code chunking:

**Extracted Relationships**:

| Relationship | Example | Source |
|--------------|---------|--------|
| imports | `auth_module --[imports]--> jwt` | Import statements |
| contains | `UserController --[contains]--> login` | Class-method hierarchy |
| defined_in | `authenticate --[defined_in]--> auth_module` | File-symbol mapping |

**Implementation**: `CodeMetadataExtractor` in `graph_extractors.py`

**Advantages**:
- Zero additional API calls
- Deterministic results
- Fast extraction
- Works on all supported languages

### 2. LLM-Based Extraction (Thorough, Semantic)

Uses an LLM to identify entities and relationships from text content:

**Extraction Prompt**:
```
Extract key entity relationships from the following text.
Return triplets in format: SUBJECT | SUBJECT_TYPE | PREDICATE | OBJECT | OBJECT_TYPE

Rules:
- SUBJECT and OBJECT are entity names
- SUBJECT_TYPE and OBJECT_TYPE are classifications
- PREDICATE is the relationship type
```

**Implementation**: `LLMEntityExtractor` in `graph_extractors.py`

**Advantages**:
- Captures conceptual relationships
- Understands natural language descriptions
- Identifies entities in documentation
- Provides entity type classifications

**Configuration** — enabling LLM extraction is a `config.yaml` choice
(`extraction.mode`); only the model and per-chunk cap are env vars:

```yaml
extraction:
  mode: "subagent"   # off (default) | subagent (free) | auto | provider (BILLABLE)
```

```bash
export GRAPH_EXTRACTION_MODEL=claude-haiku-4-5  # Fast, cost-effective
export GRAPH_MAX_TRIPLETS_PER_CHUNK=10  # Prevent graph explosion
```

### Combining Both Methods

When both methods are enabled (recommended for codebases):

1. **Code metadata extraction** runs first (fast, structural)
2. **LLM extraction** adds semantic relationships (thorough)
3. Results are merged, with duplicates removed

---

## Query Modes

GraphRAG introduces two new query modes:

### GRAPH Mode (Graph-Only)

Retrieves documents based purely on entity relationships.

```bash
brainpalace query "what uses QueryService" --mode graph
```

**How It Works**:
1. Extract entity names from query ("QueryService")
2. Find matching entities in graph
3. Traverse relationships (up to `GRAPH_TRAVERSAL_DEPTH` hops)
4. Return documents linked to discovered entities

**Best For**:
- "What calls X?"
- "What does Y import?"
- "Classes that extend Z"
- Dependency exploration

### MULTI Mode (Comprehensive Fusion)

Combines all three retrieval methods with Reciprocal Rank Fusion.

```bash
brainpalace query "authentication implementation with dependencies" --mode multi
```

**How It Works**:
1. Run vector search (semantic similarity)
2. Run BM25 search (keyword matching)
3. Run graph search (relationship traversal)
4. Fuse results using RRF scoring
5. Return top-k combined results

**Best For**:
- Complex queries needing multiple perspectives
- "Complete overview of X"
- Queries mixing content and structure

---

## Reciprocal Rank Fusion

Multi-mode queries use **Reciprocal Rank Fusion (RRF)** to combine results from different retrieval methods.

### The RRF Formula

```
RRF_score = sum(1 / (k + rank_i)) for each retriever i
```

Where:
- `k` is a constant (default: 60)
- `rank_i` is the result's position in retriever i's ranking

### Why RRF Works

RRF elegantly handles the score normalization problem:

| Problem | RRF Solution |
|---------|--------------|
| Different score scales | Only ranks matter, not raw scores |
| Missing results | Absent results contribute 0 |
| Retriever bias | Equal weight by default |

### Example

A document appears at:
- Vector search: rank 2
- BM25 search: rank 5
- Graph search: rank 1

RRF score (k=60):
```
1/(60+2) + 1/(60+5) + 1/(60+1) = 0.016 + 0.015 + 0.016 = 0.047
```

A document appearing in all three retrievers at high positions scores higher than one appearing in only one retriever, even at rank 1.

### Configuring RRF

```bash
export GRAPH_RRF_K=60  # Default value
```

Lower k values give more weight to top-ranked results. Higher k values smooth out ranking differences.

---

## Structural Queries

Beyond `--mode graph` retrieval, three CLI verbs answer structural questions
directly against the SQLite graph store — no embedding call, no chroma
requirement, works on any backend:

```bash
brainpalace graph path <src> <dst> --json    # shortest edge paths between two nodes
brainpalace graph impact <node> --json       # what transitively depends on the node
brainpalace graph cochange <file> --json     # files that change together (git history)
```

**Purpose:** answer structural questions the flat search modes cannot — how
two code entities are connected (`path`), what would be affected by changing
one (`impact`), and which files historically change together (`cochange`,
from git history). Nodes are referenced by canonical id (absolute path or
`path:fqname`) or a unique display name; an ambiguous name fails with the
candidate ids listed.

**Examples**:

```bash
brainpalace graph path graph_store.py sqlite_graph_store.py
brainpalace graph impact brainpalace_server/storage/sqlite_graph_store.py --max-depth 2
brainpalace graph cochange brainpalace_server/storage/graph_store.py
```

On failure, stdout is `{"error": ...}` with a non-zero exit — the same
contract as `query --json`. `cochange` needs `git_indexing` enabled; these
endpoints are also mirrored in the dashboard's node detail panel (Impact and
Co-change sections).

---

## Best Practices

### 1. Choose the Right Query Mode

| Query Type | Recommended Mode |
|------------|------------------|
| Exact function names | `bm25` |
| Conceptual questions | `vector` |
| Technical documentation | `hybrid` |
| Dependency questions | `graph` |
| Complex investigations | `multi` |

### 2. Tune Traversal Depth

```bash
# Default: 2 hops
brainpalace query "imports of auth module" --mode graph

# Deeper exploration: 3-4 hops
export GRAPH_TRAVERSAL_DEPTH=3
brainpalace query "full dependency chain" --mode graph
```

**Guidance**:
- Depth 1: Direct relationships only
- Depth 2: One intermediate entity (default)
- Depth 3-4: Deep exploration (may be slow)

### 3. Balance Extraction Methods

| Scenario | Configuration |
|----------|---------------|
| Code-only repository | `CODE_METADATA=true`, `LLM_EXTRACTION=false` |
| Documentation-only | `CODE_METADATA=false`, `LLM_EXTRACTION=true` |
| Mixed codebase | Both enabled (default) |
| Cost-sensitive | `CODE_METADATA=true`, `LLM_EXTRACTION=false` |

### 4. Monitor Graph Size

Check graph statistics via status endpoint:

```bash
brainpalace status
```

Output includes:
```json
{
  "graph_index": {
    "enabled": true,
    "initialized": true,
    "entity_count": 150,
    "relationship_count": 320,
    "store_type": "simple"
  }
}
```

### 5. Rebuild Graph When Needed

Graph index can be rebuilt independently:

```bash
# Reset everything
brainpalace reset --yes

# Re-index with graph enabled
export ENABLE_GRAPH_INDEX=true
brainpalace index /path/to/project
```

---

## Performance Considerations

### Indexing Impact

GraphRAG adds overhead during indexing:

| Configuration | Indexing Time | Reason |
|---------------|---------------|--------|
| GraphRAG disabled | Baseline | No graph processing |
| Code metadata only | +10-20% | AST traversal |
| LLM extraction | +50-100% | API calls per chunk |
| Both enabled | +60-120% | Combined overhead |

### Query Latency

| Mode | Typical Latency | Notes |
|------|-----------------|-------|
| bm25 | 10-50ms | Fastest |
| vector | 800-1500ms | Embedding generation |
| hybrid | 1000-1800ms | Parallel + fusion |
| graph | 500-1200ms | Graph traversal |
| multi | 1500-2500ms | All three + RRF |

### Memory Usage

Graph storage adds memory requirements:

| Store Type | Memory Footprint | Use Case |
|------------|------------------|----------|
| simple | ~100MB per 10K entities (whole graph in RAM) | Small/medium graphs, zero-setup default |
| sqlite | Bounded — rows loaded per query, not all-at-once | Large graphs, session graphs, temporal queries |

### Storage Backends

BrainPalace ships two graph backends. Both implement the same property-graph
surface, so retrieval results are identical (verified by a parity test) — the
choice is operational, not behavioural.

**`sqlite` (default) — persistent, incremental, temporal (Phase 090).** A plain
`sqlite3`-backed store (`graph_store.db`, stdlib only — no native build, no
external DB). Each triplet is written incrementally (no whole-file rewrite) and
rows are loaded per query, so memory stays bounded as the graph grows. `brainpalace init`
defaults to `sqlite`; it is the recommended backend for all new projects.

**`simple` — opt-in lightweight in-memory mode.** An in-memory property graph
persisted to JSON (`graph_store_llamaindex.json`) under the project state dir.
Zero configuration, no external database, whole graph loaded on boot and
rewritten on every persist. Best for small/medium graphs or environments where
persistence is not needed. Switch to it with:

```yaml
graphrag:
  enabled: true
  store_type: "simple"
```

On the **first** boot with `store_type: sqlite`, an existing `simple` JSON graph
is migrated into the DB once (the JSON is left in place for rollback safety).

*Temporal validity.* SQLite edges carry `valid_from` / `valid_until`. An edge
can be **invalidated** (closed) without deletion, queries return only
currently-valid edges by default, and an entity's full edge history is available
as a **timeline** — the substrate for supersedes-chains and stale-decision
penalties (Phase 140).

> ⚠️ **Temporal features require `sqlite`.** With `store_type: simple`,
> temporal validity is **unavailable**: no `valid_from`/`valid_until`, no
> invalidation, no `as_of` / point-in-time queries, and no decision
> supersession history. `simple` behaves as `sqlite` with every edge
> permanently open. `brainpalace init` now defaults to `sqlite` so these work.

The embedded-DB (Kuzu) backend earlier versions exposed has been removed; an
unknown `store_type` left in an old config is downgraded to `simple`
automatically with a warning.

---

## Troubleshooting

### Graph queries return empty

A `graph`-mode query no longer errors when GraphRAG is disabled — it returns
empty, like `bm25`/`vector` on an empty index. `ENABLE_GRAPH_INDEX` gates
**building** the graph (its cost), not the query. To get results, ensure
`ENABLE_GRAPH_INDEX=true` (or `graphrag.enabled: true`) so the graph is built;
**building** operations (the `rebuild_graph` index endpoint) still refuse when
it is off.

### Empty Graph Results

If graph queries return no results:

1. Check if graph indexing completed: `brainpalace status`
2. Verify entity extraction: Look for `entity_count > 0`
3. Try simpler queries: "what imports X" instead of complex queries

### Slow LLM Extraction

If indexing is too slow with LLM extraction:

1. Disable LLM extraction: set `extraction.mode: "off"` in `config.yaml`
2. Use a faster model: `GRAPH_EXTRACTION_MODEL=claude-haiku-4-5`
3. Reduce triplets per chunk: `GRAPH_MAX_TRIPLETS_PER_CHUNK=5`

### Graph Store Corruption

If graph queries fail with storage errors:

```bash
# Clear graph and rebuild
brainpalace reset --yes
brainpalace index /path/to/project
```

---

## Next Steps

- [Code Indexing Deep Dive](CODE_INDEXING.md) - How AST metadata feeds GraphRAG
- [API Reference](API_REFERENCE.md) - Graph endpoints and parameters
- [Configuration Reference](CONFIGURATION.md) - All GraphRAG settings
