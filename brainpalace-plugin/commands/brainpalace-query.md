---
name: brainpalace-query
description: Search indexed documents with a natural language or keyword query
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: top-k
    type: integer
    required: false
    default: 5
  - name: threshold
    type: float
    required: false
    default: 0.3
  - name: mode
    type: choice
    required: false
    default: hybrid
  - name: alpha
    type: float
    required: false
    default: 0.5
  - name: json
    type: bool
    required: false
    default: false
  - name: full
    type: bool
    required: false
    default: false
  - name: scores
    type: bool
    required: false
    default: false
  - name: source-types
    type: text
    required: false
    default: ""
  - name: languages
    type: text
    required: false
    default: ""
  - name: file-paths
    type: text
    required: false
    default: ""
  - name: no-time-decay
    type: bool
    required: false
    default: false
  - name: language
    type: text
    required: false
    default: ""
skills:
  - using-brainpalace
last_validated: 2026-06-24
---

# BrainPalace Query

## Purpose

Searches indexed documents with a natural language or keyword query. Retrieval
mode selects the strategy: `vector` (semantic similarity), `bm25` (keyword
matching), `hybrid` (vector + bm25, the default), `graph` (knowledge-graph
relationships, requires `ENABLE_GRAPH_INDEX=true`), or `multi` (fusion of
vector + bm25 + graph).

In `graph`/`multi` modes results carry graph context in the `related_entities` and
`relationship_path` response fields. Filtering the graph walk by entity or
relationship type (`entity_types` / `relationship_types`) is available **only via
the HTTP API**, not this CLI command; traversal depth is fixed server-side by
`GRAPH_TRAVERSAL_DEPTH` (default 2), never per query.

## Usage

```
/brainpalace:brainpalace-query "<query text>" [--mode <mode>] [--top-k <n>] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| QUERY_TEXT | Yes | — | The search query (positional) |
| --url | No | from config or http://127.0.0.1:8000 | BrainPalace server URL |
| --top-k, -k | No | 5 | Number of results to return |
| --threshold, -t | No | 0.3 | Minimum similarity threshold (0-1) |
| --mode, -m | No | hybrid | Retrieval mode: vector / bm25 / hybrid / graph / multi |
| --alpha, -a | No | 0.5 | Weight for hybrid search (1.0 = pure vector, 0.0 = pure bm25) |
| --json | No | false | Output as JSON |
| --full | No | false | Show full text content |
| --scores | No | false | Show individual vector/BM25 scores |
| --source-types | No | "" | Comma-separated source types to filter by (doc,code,test) |
| --languages | No | "" | Comma-separated programming languages to filter by |
| --file-paths | No | "" | Comma-separated file path patterns to filter by (wildcards supported) |
| --no-time-decay | No | false | Disable age-weighted ranking for this query |
| --language | No | "" | BM25 query language override (ISO 639-1, e.g. en, de, hr) |

## Execution

```bash
brainpalace query "how to use python" --mode hybrid --top-k 8
```

## Output

### JSON Schema (stdout)

```json
{
  "query": "<text>",
  "total_results": 0,
  "query_time_ms": 0.0,
  "results": [
    {"text": "<chunk snippet>", "source": "<file path>",
     "score": 0.0, "chunk_id": "<id>"}
  ]
}
```

Per-result keys are `text` and `source` (NOT `content`/`file_path`).

On failure, `--json` instead emits `{"error": "...", "detail": ..., "hint": "..."}`
(no `results` key) AND exits non-zero. Consumers must check the exit code, not
just the presence of `results`.

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-status` | Check the server is healthy before querying |
| `/brainpalace:brainpalace-index` | Index documents to search over |
| `/brainpalace:brainpalace-ai-guide` | Print AI usage guidance (search rules, modes) |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config or http://127.0.0.1:8000) |
| --top-k | integer | 5 | Number of results to return (default: 5) |
| --threshold | float | 0.3 | Minimum similarity threshold 0-1 (default: 0.3) |
| --mode | choice | hybrid | Retrieval mode: 'vector' (semantic similarity), 'bm25' (keyword matching), 'hybrid' (vector+bm25), 'graph' (knowledge graph relationships; empty unless the graph is built — ENABLE_GRAPH_INDEX gates building it), 'multi' (fusion of vector+bm25+graph), 'compute' (set-level aggregation over typed numeric records; empty unless record extraction has populated them), 'scan' (deterministic term counts over the archived session transcripts; 'which week did I mention X most'; empty when the session archive is off), 'absence' (anti-join over typed records: subjects present under one partition value but absent under another, e.g. 'distance but not duration'; empty when no two stored values resolve), 'timeline' (walk an entity's edge-validity/supersession history: how a belief/fact evolved, e.g. 'how did the auth decision evolve'; empty when the named entity resolves to no graph node), Default: hybrid. |
| --alpha | float | 0.5 | Weight for hybrid search (1.0 = pure vector, 0.0 = pure bm25, default: 0.5) |
| --json | bool | false | Output as JSON |
| --full | bool | false | Show full text content |
| --scores | bool | false | Show individual vector/BM25 scores |
| --source-types | text | "" | Comma-separated source types to filter by (doc,code,test) |
| --languages | text | "" | Comma-separated programming languages to filter by |
| --file-paths | text | "" | Comma-separated file path patterns to filter by (wildcards supported) |
| --no-time-decay | bool | false | Disable age-weighted ranking for this query (newer-ranked-higher). |
| --language | text | "" | BM25 query language override (ISO 639-1, e.g. en, de, hr). Overrides the project bm25.language for this query only. |
<!--/GENERATED-->

## Modes
<!--GENERATED:modes-->
| Mode | Description |
|------|-------------|
| `vector` | Semantic similarity search |
| `bm25` | Keyword matching |
| `hybrid` | Vector + BM25 fusion (default) |
| `graph` | Knowledge graph relationships (empty unless the graph is built) |
| `multi` | Fusion of vector + BM25 + graph via RRF |
| `compute` | Set-level aggregation over typed numeric records |
| `scan` | Deterministic term counts over archived session transcripts (empty when the session archive is off) |
| `absence` | Anti-join over typed records (empty when no two stored values resolve) |
| `timeline` | Edge-validity/supersession history walk (empty when the entity resolves to no graph node) |
<!--/GENERATED-->
