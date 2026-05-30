---
last_validated: 2026-05-30
---

# Changelog

All notable changes to BrainPalace are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning is **CalVer** `YY.M.N` — 2-digit year · month · Nth release that
month (the counter resets monthly). It looks like SemVer but is not.

---

## [Unreleased]

## [26.5.1] - 2026-05-30

First public release of BrainPalace.

### Highlights

- **Hybrid retrieval** — BM25 + vector + GraphRAG, fused (`hybrid`/`multi`) or
  selectable per call (`bm25`/`vector`/`graph`).
- **Session intelligence** — curated memory (`remember`/`recall`,
  markdown-truth) + session-start context injection; session indexing/extraction
  into searchable summaries, decisions, and a typed knowledge graph;
  cross-session linking that supersedes stale decisions and promotes durable
  ones into memory.
- **Persistent SQLite graph backend** with temporal validity (per-edge validity
  windows, `invalidate`, `timeline`).
- **Time-decay ranking**, **git-history indexing** (commit messages + diff
  stats), and an opt-in **LSP cross-reference** symbol graph.
- **AST-aware code chunking** (Python, TypeScript, JavaScript, Java, Kotlin, C,
  C++, C#, Go, Rust, Swift), optional **LLM code summaries**, opt-in
  **cross-encoder reranking**.
- **Multi-instance** (one server per project, auto port allocation +
  `.brainpalace/runtime.json` discovery), **file watcher**, **incremental
  indexing**, **embedding cache**.
- **Interfaces** — CLI (`brainpalace` / `bp`), opt-in **MCP server**, and a
  **Claude Code plugin** (30 slash commands, 3 agents, 2 skills).
- **Pluggable providers** — embeddings (OpenAI · Cohere · Ollama), summarisation
  (Anthropic · OpenAI · Gemini · Grok · Ollama); fully-local via Ollama.
