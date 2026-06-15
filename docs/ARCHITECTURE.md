---
last_validated: 2026-06-15
---

# BrainPalace System Architecture

This document provides a comprehensive overview of BrainPalace's architecture, design decisions, and unique value proposition in the RAG ecosystem.

## Table of Contents

- [Executive Summary](#executive-summary)
- [Why BrainPalace?](#why-brainpalace)
- [High-Level Architecture](#high-level-architecture)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Key Design Decisions](#key-design-decisions)
- [Comparison with Alternatives](#comparison-with-alternatives)

---

## Executive Summary

BrainPalace is a RAG (Retrieval-Augmented Generation) system designed specifically for AI coding assistants. It combines three retrieval paradigms into a unified, per-project knowledge system:

1. **BM25 Keyword Search** - Fast, precise matching for technical terms, function names, and error codes
2. **Semantic Vector Search** - Deep understanding of concepts and natural language queries
3. **GraphRAG Knowledge Graph** - Relationship-aware retrieval for dependencies, hierarchies, and connections

Unlike generic RAG solutions, BrainPalace is built with code-first priorities: AST-aware chunking, per-project isolation, and seamless integration with Claude Code.

### Key Differentiators

| Feature | BrainPalace | Generic RAG |
|---------|-------------|-------------|
| Code Understanding | AST-aware chunking for 8+ languages | Text-based splitting |
| Search Modes | 5 modes (BM25, Vector, Hybrid, Graph, Multi) | Usually 1-2 modes |
| Project Isolation | Per-project servers with auto-discovery | Shared instance |
| Knowledge Graphs | GraphRAG with entity extraction | Not available |
| Claude Integration | Native plugin and skill | Manual integration |

---

## Why BrainPalace?

### The Problem with Generic RAG

Traditional RAG systems treat all content as text. This works for documentation but fails for codebases:

- **Function boundaries ignored**: A function split mid-body loses context
- **No structural awareness**: Class hierarchies and import relationships are invisible
- **Single search mode**: Either keyword OR semantic, not both
- **No relationship tracking**: "What calls this function?" is unanswerable

### BrainPalace's Solution

BrainPalace treats code as a first-class citizen with:

1. **AST-Aware Chunking**: Uses tree-sitter to split code at semantic boundaries (functions, classes, methods)
2. **Hybrid Search**: Combines BM25 precision with vector semantics in a single query
3. **GraphRAG**: Builds a knowledge graph of entities and relationships for structural queries
4. **Per-Project Isolation**: Each project gets its own index with automatic port management

---

## High-Level Architecture

```
                                    +------------------------+
                                    |    Claude Code         |
                                    |    (Plugin/Skill)      |
                                    +------------------------+
                                              |
                                              v
+------------------+              +------------------------+
|  brainpalace-cli |  REST API   |  brainpalace-server    |
|                  |------------>|                        |
| - init           |             | FastAPI + Uvicorn      |
| - start/stop     |             +------------------------+
| - query          |                       |
| - index          |       +---------------+---------------+
| - status         |       |               |               |
+------------------+       v               v               v
                    +-----------+   +-----------+   +-----------+
                    | BM25      |   | ChromaDB  |   | GraphRAG  |
                    | Index     |   | Vectors   |   | Knowledge |
                    +-----------+   +-----------+   +-----------+
                          |               |               |
                          +-------+-------+-------+-------+
                                  |
                                  v
                         +----------------+
                         | Fusion Engine  |
                         | (RRF Scoring)  |
                         +----------------+
```

### Component Responsibilities

| Component | Role |
|-----------|------|
| **brainpalace-cli** | User-facing CLI for all operations |
| **brainpalace-server** | FastAPI REST API server handling indexing and queries |
| **BM25 Index** | Keyword-based retrieval using `bm25s` with per-language `TextAnalyzer` |
| **ChromaDB** | Vector similarity search with OpenAI embeddings |
| **GraphRAG** | Knowledge graph for entity relationships |
| **Fusion Engine** | Combines results using Reciprocal Rank Fusion |
| **MCP Server** (opt-in) | stdio shim — `brainpalace mcp` — exposes 5 read-only tools over the Model Context Protocol so non-Claude-Code AI clients (VS Code native / GitHub Copilot, Cursor, Kilo Code, Cline, Continue, Zed) call the HTTP server through typed tool calls instead of shell-outs. Lives at `brainpalace-cli/brainpalace_cli/mcp_server/`; full setup in [`MCP_SETUP.md`](MCP_SETUP.md). |

---

## Core Components

### 1. Document Loader

The document loader handles file discovery and content extraction.

**Location**: `brainpalace-server/brainpalace_server/indexing/document_loader.py`

**Capabilities**:
- Loads documents (.md, .txt, .pdf, .html, .rst)
- Loads code files (.py, .ts, .js, .java, .go, .rs, .c, .cpp, .cs)
- Automatic language detection via file extension and content patterns
- Metadata extraction (file size, path, source type)

**Supported Languages**: Python, TypeScript, JavaScript, Java, Go, Rust, C, C++, C#, Kotlin, Swift

### 2. Chunking Pipeline

The chunking system splits content into searchable units while preserving context.

**Location**: `brainpalace-server/brainpalace_server/indexing/chunking.py`

**Two Chunking Modes**:

| Mode | Used For | Strategy |
|------|----------|----------|
| **ContextAwareChunker** | Documents | Paragraph/sentence boundaries with overlap |
| **CodeChunker** | Source Code | AST-aware boundaries (function, class, method) |

**Code Chunker Features**:
- Uses LlamaIndex CodeSplitter with tree-sitter parsing
- Preserves symbol boundaries (never splits a function mid-body)
- Extracts rich metadata: symbol name, kind, line numbers, docstrings
- Generates optional LLM summaries for improved semantic search

### 3. Embedding Generator

Generates vector embeddings for semantic search.

**Location**: `brainpalace-server/brainpalace_server/indexing/embedding.py`

**Configuration**:
- Model: `text-embedding-3-large` (3072 dimensions)
- Batch processing: 100 chunks per batch
- Caching for repeated queries

### 4. Vector Store (ChromaDB)

Persistent vector storage for similarity search.

**Location**: `brainpalace-server/brainpalace_server/storage/vector_store.py`

**Features**:
- Thread-safe async operations
- Cosine similarity scoring
- Metadata filtering (source type, language, file path)
- Upsert support for incremental updates

### 5. BM25 Index

Keyword-based retrieval for exact term matching.

**Location**: `brainpalace-server/brainpalace_server/indexing/bm25_index.py`

**Features**:
- Persistent disk-based index
- `bm25s` scoring engine (direct, no LlamaIndex wrapper)
- Per-language tokenization pipeline — see below
- Language and source type filtering
- Sub-50ms query latency

#### BM25 tokenization pipeline

BrainPalace owns the tokenization pipeline via a pluggable **`TextAnalyzer`**
protocol (defined in `indexing/text_analysis/base.py`). Every analyzer runs the
same four-stage pipeline: **normalize** (NFC + lowercase) → **tokenize** (Unicode
`\w+`) → **stopword removal** → **stem or lemmatize**. The same analyzer instance
is used for both indexing and querying, guaranteeing index/query symmetry.

| Component | Location | Role |
|-----------|----------|------|
| `TextAnalyzer` protocol | `text_analysis/base.py` | Interface: `analyze(text) -> list[str]` |
| `SNOWBALL` table + `SnowballAnalyzer` | `text_analysis/snowball.py` | 27 languages via PyStemmer |
| `CroatianStemAnalyzer` / `CroatianLemmaAnalyzer` | `text_analysis/croatian.py` | Vendored Ljubešić–Pandžić stemmer; optional `simplemma` lemma tier (`hbs` data) |
| `get_analyzer(code, engine)` | `text_analysis/registry.py` | Routes ISO 639-1 code + engine to the right analyzer; unknown codes fall back to English |
| Stopwords | `text_analysis/stopwords.py` | `stopwordsiso` (~57 languages) |
| Language detection | `text_analysis/detect.py` | Opt-in `py3langid` per-document detection |

The analyzer fingerprint (language code + engine) is persisted alongside the
corpus. If the fingerprint changes on server start — because `language` or
`engine` was reconfigured — the BM25 index is automatically rebuilt from the
stored corpus, so the index never drifts out of sync with its tokenization.

### 6. GraphRAG Index

Knowledge graph for relationship-aware retrieval.

**Location**: `brainpalace-server/brainpalace_server/indexing/graph_index.py`

**Features**:
- Entity extraction (LLM-based and code metadata)
- Relationship storage (imports, contains, calls, extends)
- Graph traversal for multi-hop queries
- Two interchangeable storage backends behind one `GraphStoreManager` surface
  (`storage/graph_store.py`), selected by `GRAPH_STORE_TYPE`:
  - **`simple`** (default): `SimplePropertyGraphStore` — in-memory, whole-graph
    JSON persistence. Zero-setup.
  - **`sqlite`** (`storage/sqlite_graph_store.py`, Phase 090): persistent
    `sqlite3` property graph (`graph_store.db`, stdlib only). Incremental
    per-triplet writes (no whole-file rewrite), bounded per-query load, and a
    **temporal-validity model** — every edge has `valid_from`/`valid_until`,
    supports `invalidate()`, `as_of` time-travel queries, and per-entity
    `timeline()`. Duck-types the same property-graph API the retrieval and
    write paths consume, so GRAPH results are identical to `simple` (parity-
    tested). On first use it migrates an existing JSON graph into the DB once.

### 7. Query Service

Orchestrates search across all indexes.

**Location**: `brainpalace-server/brainpalace_server/services/query_service.py`

**Query Modes**:

| Mode | Description | Use Case |
|------|-------------|----------|
| `bm25` | Keyword-only search | Technical terms, function names |
| `vector` | Semantic-only search | Concepts, explanations |
| `hybrid` | BM25 + Vector with Relative Score Fusion | Comprehensive results |
| `graph` | Knowledge graph traversal | Dependencies, relationships |
| `multi` | All three with Reciprocal Rank Fusion | Most comprehensive |

### 8. Session & Code Intelligence (Phases 030–160)

Layered on the core stack; each subsystem is opt-in and has a dedicated guide.

| Subsystem | Location | Role |
|---|---|---|
| Curated memory | `services/memory_service.py` | Markdown source-of-truth + rebuildable Chroma shadow; `remember`/`recall`, query boost. ([MEMORY.md](MEMORY.md)) |
| Session-start context | `services/session_context_service.py` | Budget-capped project facts + memory for SessionStart injection. ([SESSION_CONTEXT.md](SESSION_CONTEXT.md)) |
| Session indexing | `indexing/session_loader.py`, `session_chunker.py`, `services/session_index_service.py` | JSONL transcripts → `session_turn` chunks + watcher. |
| Session extraction | `services/session_extract_service.py`, `session_triplet_types.py`, `session_linker.py` | Persist summaries/decisions/triplets (typed graph), supersession + promotion (no server LLM). ([SESSION_INDEXING.md](SESSION_INDEXING.md), [GRAPH_TAXONOMY.md](GRAPH_TAXONOMY.md)) |
| Git history | `indexing/git_loader.py`, `git_chunker.py`, `services/git_history_index_service.py` | Commits → `git_commit` chunks, incremental. ([GIT_HISTORY.md](GIT_HISTORY.md)) |
| LSP cross-refs | `brainpalace_server/lsp/` | Opt-in typed symbol graph (calls/types/defined-at) from a language server. ([LSP_INTEGRATION.md](LSP_INTEGRATION.md)) |
| Ranking signals | `services/query_service.py` | Time-decay (`created_at`) + stale-decision penalty layered into fusion. |

---

## Data Flow

### Indexing Flow

```
User Command: brainpalace index /path/to/project

1. Document Loading
   /path/to/project --> DocumentLoader --> LoadedDocument[]

2. Type Detection
   LoadedDocument --> LanguageDetector --> {source_type, language}

3. Chunking
   Documents --> ContextAwareChunker --> TextChunk[]
   Code Files --> CodeChunker (AST) --> CodeChunk[]

4. Embedding
   Chunks --> EmbeddingGenerator --> embeddings[]

5. Storage (Parallel)
   embeddings --> ChromaDB (vectors)
   chunks --> BM25Index (keywords)
   chunks --> GraphIndex (entities/relationships) [if enabled]
```

### Query Flow

```
User Query: brainpalace query "how does authentication work" --mode hybrid

1. Query Processing
   "how does..." --> QueryRequest{mode=hybrid, top_k=5}

2. Parallel Retrieval
   QueryRequest --> VectorSearch --> vector_results[]
   QueryRequest --> BM25Search --> bm25_results[]

3. Fusion (Hybrid Mode)
   vector_results + bm25_results --> RelativeScoreFusion --> fused_results[]

4. Ranking & Filtering
   fused_results --> RankByScore --> top_k results

5. Response
   results --> QueryResponse{results, query_time_ms}
```

---

## Key Design Decisions

### 1. Per-Project Isolation

**Decision**: Each project runs its own BrainPalace server with isolated indexes.

**Rationale**:
- No context pollution between projects
- Automatic port allocation prevents conflicts
- Server discovery via runtime.json enables multi-agent workflows
- Clean shutdown releases all resources

**Implementation**: `.brainpalace/` directory per project stores state, indexes, and runtime info.

`brainpalace init` writes CLI/runtime state such as `.brainpalace/config.json` and `runtime.json`, while provider/search configuration for setup flows is typically authored in `.brainpalace/config.yaml`; both files live under the same `.brainpalace/` root.

### 2. AST-Aware Chunking

**Decision**: Use tree-sitter for code parsing instead of text-based splitting.

**Rationale**:
- Functions and classes stay intact
- Symbol metadata (name, kind, line numbers) improves search relevance
- Enables structural queries ("find all methods in class X")
- Supports 8+ languages with consistent quality

### 3. Hybrid Search Default

**Decision**: Hybrid mode (BM25 + Vector) is the default search mode.

**Rationale**:
- BM25 excels at exact matches (function names, error codes)
- Vector search excels at semantic understanding
- Fusion provides best of both worlds
- Alpha parameter allows tuning (0 = pure BM25, 1 = pure vector)

### 4. GraphRAG as Optional

**Decision**: GraphRAG is disabled by default; users opt-in via configuration.

**Rationale**:
- Entity extraction adds indexing latency
- Graph storage requires additional memory
- Many use cases don't need relationship queries
- Progressive enhancement: enable when needed

### 5. LlamaIndex Foundation

**Decision**: Build on LlamaIndex for graph stores and code chunking, while owning
the BM25 layer directly via `bm25s` and a custom `TextAnalyzer` pipeline.

**Rationale**:
- Battle-tested components (CodeSplitter, graph stores, embeddings)
- Active community and maintenance
- Plugin ecosystem
- Owning BM25 tokenization enables per-language analysis and symmetric
  index/query tokenization — not possible via the LlamaIndex BM25Retriever
  wrapper that was replaced
- Focus on code-specific innovations, not RAG basics

---

## Comparison with Alternatives

### BrainPalace vs. LangChain RAG

| Aspect | BrainPalace | LangChain RAG |
|--------|-------------|---------------|
| Code Support | AST-aware, 8+ languages | Text-based only |
| Search Modes | 5 modes with fusion | Usually 1-2 modes |
| Graph Support | Built-in GraphRAG | Requires custom setup |
| Deployment | Per-project servers | Shared service |
| Claude Integration | Native plugin | Manual integration |

### BrainPalace vs. Copilot Workspace

| Aspect | BrainPalace | Copilot Workspace |
|--------|-------------|-------------------|
| Customization | Full control | Black box |
| Index Content | Your choice | Predetermined |
| Search Tuning | Mode/threshold control | None |
| Local Control | Full | Cloud-dependent |
| Cost | OpenAI embeddings only | Subscription |

### BrainPalace vs. Custom ChromaDB Setup

| Aspect | BrainPalace | Custom ChromaDB |
|--------|-------------|-----------------|
| Code Understanding | Built-in AST | DIY |
| BM25 Search | Included | Separate system |
| Graph Search | Included | Not available |
| CLI/API | Ready to use | Build yourself |
| Multi-project | Automatic | Manual setup |

---

## Next Steps

- [GraphRAG Integration Guide](GRAPHRAG_GUIDE.md) - Deep dive into knowledge graph features
- [Code Indexing Deep Dive](CODE_INDEXING.md) - AST-aware chunking explained
- [API Reference](API_REFERENCE.md) - Complete REST API documentation
- [Configuration Reference](CONFIGURATION.md) - All configuration options
