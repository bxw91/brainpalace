---
name: brainpalace-multi
description: Search using multi-mode fusion combining all search modes
parameters:
  - name: query
    description: The comprehensive search query
    required: true
  - name: top-k
    description: Number of results to return (1-20)
    required: false
    default: 5
  - name: threshold
    description: Minimum relevance score (0.0-1.0)
    required: false
    default: 0.3
skills:
  - using-brainpalace
last_validated: 2026-05-30
---

# BrainPalace Multi-Mode Search

## Purpose

Performs multi-mode fusion search combining BM25 keyword matching, semantic vector search, and GraphRAG relationships using Reciprocal Rank Fusion (RRF). This is the most comprehensive search mode, finding results from all angles.

Multi-mode search is ideal for:
- Complex queries requiring comprehensive results
- When you want both content matches AND relationships
- Investigating full implementation details
- Combining technical terms with conceptual understanding
- When you're not sure which mode would be best

## Usage

```
/brainpalace:brainpalace-multi <query> [--top-k <n>] [--threshold <t>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| query | Yes | - | The comprehensive search query |
| --top-k, -k | No | 5 | Number of results (1-20) |
| --threshold, -t | No | 0.3 | Minimum relevance score (0.0-1.0) |
| --source-types | No | - | Filter by source type (doc,code,test) |
| --languages | No | - | Filter by programming language |
| --file-paths | No | - | Filter by file path patterns (wildcards) |
| --scores | No | false | Show individual vector/BM25 scores |
| --full | No | false | Show full text content |
| --json | No | false | Output as JSON |
| --url | No | from config | Server URL (env: BRAINPALACE_URL) |

### How Multi-Mode Works

1. **BM25 Search**: Finds exact term matches
2. **Vector Search**: Finds semantically similar content
3. **Graph Search**: Finds related entities and relationships
4. **RRF Fusion**: Combines results using Reciprocal Rank Fusion

```
RRF_score(d) = Σ 1/(k + rank_i(d))
```

Where `k` is a constant (typically 60) and `rank_i(d)` is the rank of document `d` in result list `i`.

## Execution

### Pre-flight Check

```bash
# Verify server is running and capabilities
brainpalace status
```

Multi-mode works best with all indices available:
- BM25 index: Built during indexing
- Vector index: Requires embedding provider
- Graph index: Requires `ENABLE_GRAPH_INDEX=true`

### Search Command

```bash
brainpalace query "<query>" --mode multi --top-k <k> --threshold <t>
```

### Examples

```bash
# Comprehensive implementation search
brainpalace query "complete authentication implementation" --mode multi

# More results for exploration
brainpalace query "error handling patterns" --mode multi --top-k 10

# Lower threshold for broader search
brainpalace query "caching strategy" --mode multi --threshold 0.2

# Payment processing with more context
brainpalace query "payment processing flow" --mode multi --top-k 8
```

## Output

### Result Format

The CLI displays results in panels showing:
- Source file path
- Relevance score (RRF-fused percentage)
- Text content excerpt

Multi-mode combines results from BM25, Vector, and Graph (if enabled) using Reciprocal Rank Fusion.

### Example Output

```
Query: complete authentication implementation
Found 3 results in 2341ms

╭─ [1] src/auth/oauth_client.py  Score: 94% ────────────────────╮
│ class OAuthClient:                                             │
│     """                                                        │
│     Complete OAuth 2.0 client implementation.                  │
│                                                                │
│     Handles authorization code flow, token refresh,            │
│     and automatic retry with exponential backoff.              │
│     """                                                        │
│                                                                │
│     def authenticate(self, code: str) -> Token:                │
│         ...                                                    │
╰────────────────────────────────────────────────────────────────╯

╭─ [2] docs/auth/oauth-guide.md  Score: 87% ────────────────────╮
│ ## OAuth 2.0 Implementation Guide                              │
│                                                                │
│ This guide covers the complete OAuth 2.0 implementation:       │
│ - Authorization Code Flow                                      │
│ - Token Management                                             │
│ - Security Best Practices                                      │
╰────────────────────────────────────────────────────────────────╯

╭─ [3] src/auth/token_manager.py  Score: 72% ───────────────────╮
│ class TokenManager:                                            │
│     """Manages token lifecycle including refresh."""           │
│                                                                │
│     def refresh_token(self, token: Token) -> Token:            │
│         ...                                                    │
╰────────────────────────────────────────────────────────────────╯
```

### Detailed Scores (with --scores flag)

Use `--scores` to see individual BM25 and vector scores:

```bash
brainpalace query "authentication" --mode multi --scores
```

Shows `[V: 0.92 B: 0.88]` after each score for debugging.

## Error Handling

### Server Not Running

```
Error: Could not connect to BrainPalace server
```

**Resolution:**
```bash
brainpalace start
```

### Graph Index Not Available

```
Warning: Graph index not enabled. Multi-mode will use BM25 + Vector only.
```

**Resolution (optional):**
```bash
export ENABLE_GRAPH_INDEX=true
brainpalace stop && brainpalace start
brainpalace reset --yes
brainpalace index /path/to/code
```

Multi-mode gracefully degrades if graph is unavailable.

**Note:** When using PostgreSQL backend, graph is automatically excluded from multi-mode results. No action needed.

### No Results Found

```
No results found above threshold 0.3
```

**Resolution:**
- Try lowering threshold: `--threshold 0.1`
- Try a more specific or broader query
- Verify documents are indexed: `brainpalace status`

### Embedding Provider Not Configured

```
Error: Embedding provider not configured (vector component requires embeddings)
```

**Resolution:**
Run `/brainpalace:brainpalace-config` to configure a provider:
- **Ollama** (FREE, local): No API keys needed
- **OpenAI** (cloud): `export OPENAI_API_KEY="sk-proj-..."`

### Index Empty

```
Warning: No documents indexed
```

**Resolution:**
```bash
brainpalace index /path/to/docs
```

## Performance Notes

| Metric | Typical Value |
|--------|---------------|
| Latency | 1500-2500ms |
| API calls | 1 embedding call |
| Best for | Comprehensive search, complex queries |

### When to Use Multi vs Other Modes

| Query Type | Recommended Mode |
|------------|------------------|
| Quick lookup of exact term | BM25 |
| Conceptual question | Vector |
| Balanced general search | Hybrid |
| **Comprehensive investigation** | **Multi** |
| Dependency/relationship query | Graph |

### Resource Usage

Multi-mode uses the most resources:
- Runs all three search modes
- Combines results with RRF
- Optional graph traversal

Consider using more targeted modes for simple queries.

## Graceful Degradation

Multi-mode adapts to available capabilities:

| Available | Modes Used |
|-----------|------------|
| BM25 + Vector + Graph | Full multi-mode |
| BM25 + Vector | Hybrid-like fusion |
| BM25 only | BM25 results only |
| Vector only | Vector results only |

**Note:** When using the PostgreSQL backend (`BRAINPALACE_STORAGE_BACKEND=postgres`), multi-mode automatically uses BM25 + Vector only (graph component is skipped). No error is raised -- multi-mode gracefully adapts.

Check server status to see available capabilities:
```bash
brainpalace status
```

## Related Commands

- `/brainpalace:brainpalace-hybrid` - Balanced BM25 + semantic
- `/brainpalace:brainpalace-graph` - Relationship-focused search
- `/brainpalace:brainpalace-bm25` - Fast keyword search
- `/brainpalace:brainpalace-vector` - Semantic concept search
