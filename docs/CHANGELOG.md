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

## [26.6.3] - 2026-06-01

### Changed
- **Session live-watcher debounce default raised 2s → 30s**
  (`session_indexing.watch_debounce_ms`). AI transcripts are written
  per-message in bursts (quiet during generation, then a burst of lines), so
  the old 2s window fired redundant re-index passes mid-turn on an in-progress
  transcript. 30s batches a whole turn; freshness is low-value here (recall
  targets *past* sessions, not the live one). Tunable per project; the archive
  deletion watcher stays at 1s.

### Internal
- **CI: GitHub Actions Node 20 → Node 24.** Bumped `actions/checkout@v6`,
  `setup-python@v6`, `cache@v5`, `upload-artifact@v7`, `codecov-action@v5`, and
  set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to carry the remaining Node 20
  actions (`arduino/setup-task`, codecov's internal `github-script`) onto
  Node 24 ahead of the 2026-06-16 default flip and 2026-09-16 removal.
- **Docs:** README usage examples (codebase / docs / graph / session memory),
  a Session Memory badge, and clarified that automatic session capture is
  Claude Code-transcript-specific (works from CLI or plugin install).

## [26.6.2] - 2026-06-01

Durable, user-curatable session archive: session indexing now reads from a
local archive copy instead of the live `~/.claude` transcripts.

### Added
- **Session archive.** On a transcript change the raw `.jsonl` is copied
  verbatim into `.brainpalace/session_archive/<YYYY-MM-DD>/`, and indexing runs
  off the archive copy. `~/.claude` is treated as read-only. Sessions survive
  Claude Code removal / auto-delete. Opt-out via `session_indexing.archive.enabled`.
- **Curation by deletion.** Deleting an archived transcript (or a dated folder)
  purges that session's index chunks and writes a tombstone, so the live source
  is never re-synced (no resurrection).
- **Provenance.** Chunks record `origin_path` (the live source) alongside
  `source_path` (the archive copy).
- **Status.** `brainpalace status` / `/status` report `archived_sessions`,
  `archived_files`, `archived_bytes`, and `tombstoned`.
- **`brainpalace reset --include-sessions`** also deletes the archive; a plain
  reset preserves it.

### Fixed
- Chunk purge used a flat multi-key ChromaDB `where` filter that ChromaDB
  rejects ("expected exactly one operator"); deletions never purged chunks.
  Wrapped in `$and`.
- Subagent transcripts carry the parent's `sessionId`, so a `session_id`-keyed
  manifest collided each parent with its subagents (undercount, broken mtime
  no-op, and a data-loss path where deleting one subagent purged the parent's
  chunks). Manifest is now keyed per file; a session is purged only when all of
  its files are gone.

## [26.6.1] - 2026-06-01

Second release: watcher/session-memory/status fixes plus first-run UX and
correctness fixes found during integration testing.

### Added

- **`index --watch` / `--watch-debounce`** — mark a folder live-watched (or
  `--watch off`); the server's `FileWatcherService` re-indexes on change with a
  tunable debounce.
- **`init --sessions` session memory** — opt-in, privacy-first indexing of this
  project's AI chat transcripts (assistant + tool turns). Default off; `init`
  prompts on a TTY, stays off non-interactively.
- **`status` per-feature view** — document indexing, file watcher (with a clear
  "0 folders — none marked watch=auto" state), session memory (on/off,
  watching/idle, session-chunk + curated-memory counts), and graph index.
- **`init --start` provider pre-flight** — validates embedding + summarization
  providers before launching, failing fast with the missing env var instead of
  crashing mid-index.

### Fixed

- **Session chunks upsert to Chroma** — the session chunker stored list
  (`role_mix`, `tools_used`, `files_touched`) and `None` metadata values that
  Chroma rejects ("Expected metadata value to be a str, int, float or bool"),
  crashing session indexing at boot on every project. Lists are now comma-joined
  and unset optional keys dropped.
- **`folders add` watch default** — bare `folders add .` now defaults to
  `--watch auto` (was `off`), matching the documented behaviour so the file
  watcher isn't left at "0 folders".
- **Summarization `api_key_env` ignored the provider** — an OpenAI-only user who
  set `summarization.provider: openai` but no `api_key_env` got
  "Set ANTHROPIC_API_KEY" and a startup crash. The conventional env var is now
  derived from the selected provider when unset (openai→`OPENAI_API_KEY`,
  cohere→`COHERE_API_KEY`, gemini→`GEMINI_API_KEY`, grok→`XAI_API_KEY`); error
  messages name the correct var.
- **`init --start` re-run** — re-running after a first run that aborted at the
  provider pre-flight now starts the server idempotently instead of hitting the
  already-initialized no-op.
- **`init --force`** — no longer overwrites a user-edited `.brainpalace/
  config.yaml` (provider/embedding/summarization/storage/graphrag settings are
  preserved; use `brainpalace config` to change providers).
- **`status` `total_documents`** — derived from persisted folder manifests, so
  it's correct even when indexing ran in the job worker. Folder `chunk_count` is
  cumulative.

### Docs

- Documented the session-memory embedding cost (50% sliding-window overlap at
  `window=4`/`stride=2`; `stride: 4` ~halves it) in `SESSION_INDEXING.md` and
  `CLAUDE.md`.

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
