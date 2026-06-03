---
last_validated: 2026-06-04
---

<div align="center">

![Code & Docs RAG](https://img.shields.io/badge/Code_%26_Docs_RAG-1f6feb?style=for-the-badge)
![Mono-repo](https://img.shields.io/badge/Mono--repo-1f6feb?style=for-the-badge)
![Session Memory](https://img.shields.io/badge/Session_Memory-1f6feb?style=for-the-badge)
![File Watcher](https://img.shields.io/badge/File_Watcher-1f6feb?style=for-the-badge)
![.gitignore-aware](https://img.shields.io/badge/.gitignore--aware-1f6feb?style=for-the-badge)

![BM25](https://img.shields.io/badge/BM25-8957e5?style=for-the-badge)
![Vector](https://img.shields.io/badge/Vector-8957e5?style=for-the-badge)
![GraphRAG](https://img.shields.io/badge/GraphRAG-8957e5?style=for-the-badge)
![Hybrid](https://img.shields.io/badge/Hybrid-8957e5?style=for-the-badge)
![Multi-mode](https://img.shields.io/badge/Multi--mode-8957e5?style=for-the-badge)
![Summaries](https://img.shields.io/badge/Summaries-8957e5?style=for-the-badge)

![CLI](https://img.shields.io/badge/CLI-d29922?style=for-the-badge)
![MCP](https://img.shields.io/badge/MCP-d29922?style=for-the-badge)
![Local LLM](https://img.shields.io/badge/Local_LLM-da3633?style=for-the-badge)
![Cloud LLM](https://img.shields.io/badge/Cloud_LLM-da3633?style=for-the-badge)
![Multi-instance](https://img.shields.io/badge/Multi--instance-6e7681?style=for-the-badge)

</div>

# BrainPalace

**Local-first RAG for code & docs, with persistent session-chat memory for AI agents.**
BM25, vector, GraphRAG, and hybrid search over your codebase and
documentation — plus persistent session-chat memory (Claude Code transcripts only), a temporal
knowledge graph, and git/LSP-aware indexing. Use it from the CLI, over MCP, or
as a Claude Code plugin. Runs fully local on Ollama, or with cloud LLMs.

## Install

Pick the path that matches how you'll use BrainPalace. All paths share the
same prerequisites and end with the same `brainpalace` CLI on your `PATH`.

### Prerequisites

| Need | Why |
|---|---|
| Python 3.10+ | CLI + server runtime |
| `pipx` | Isolated install for the CLI (`apt install pipx` or `brew install pipx`, then `pipx ensurepath`) |
| `git` | The installer fetches BrainPalace from GitHub |
| One provider — cloud key **or** Ollama | Cloud: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`, `GEMINI_API_KEY`, `GROK_API_KEY`. Local-only: a running Ollama with an embedding model pulled |
| Claude Code CLI | **Only** for the Claude Code plugin path below |

---

### Install as a Claude Code plugin

> **Recommended if you use Claude Code.** Richest UX, and it summarizes your
> sessions for free on your Claude Code subscription (Haiku — no separate API
> bill; it draws on your subscription's usage limits). Pick this over the CLI
> install if you're a Claude Code user — it installs the CLI + server for you.

Richest UX — 30 slash commands, 3 agents, 2 skills. The setup wizard inside
Claude Code installs the CLI + server, configures provider keys, initialises
the project, starts the server, and runs the first index — all from one
slash command.

1. **Install the plugin:**

   ```bash
   claude plugins marketplace add bxw91/brainpalace
   claude plugins install brainpalace@brainpalace-marketplace
   ```

   Then **restart Claude Code** (or start a new session) — the plugin's hooks
   and the `chat-session-extractor` agent load at session start.

2. **Run the setup wizard** in Claude Code:

   ```
   /brainpalace-setup
   ```

Full Claude Code reference: [`docs/PLUGIN_GUIDE.md`](docs/PLUGIN_GUIDE.md).

---

### Install as a CLI or MCP server

> **Using Claude Code? Install the plugin instead** (above) — it includes
> everything here plus free session summarization on your Claude Code
> subscription. This path is for CLI-only use or non-Claude-Code editors over MCP.

Use this if you want `brainpalace` as a command-line tool, or if you want to
connect an MCP-capable editor (Cursor, VS Code Copilot, Cline, Continue, Kilo
Code, Zed). One command does both — it will ask which MCP client to wire (or
"none" for CLI-only) along the way. Nothing runs until you answer.

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh | bash
```

That's it.

**Update later** (auto-detects pipx/uv/pip):

```bash
brainpalace update
```

```bash
brainpalace stop && brainpalace start
```

**Got more projects to index later?** The binary is installed once per machine;
every new project just needs (full setup by default — opt out with `--no-start`
/ `--no-sessions` / `--yes` for CI):

```bash
brainpalace init
```

How-to:
[`docs/INSTALL.md → Adding more projects`](docs/INSTALL.md#adding-more-projects-after-the-first-install).

**Want to remove it?** `brainpalace uninstall` runs a guided teardown — stops
servers, removes plugins + MCP entries, then asks before deleting per-project
and global state, and prints any leftover step:

```bash
brainpalace uninstall
```

If the binary is already gone, the bash mirror does the same:

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/uninstall.sh | bash
```

Full teardown reference:
[`docs/INSTALL.md → Full uninstall (teardown)`](docs/INSTALL.md#full-uninstall-teardown).

---

### Need more control?

CI / no-TTY, step-by-step manual install, low-level `install.sh` flags,
install for other AI runtimes (Codex, OpenCode, Gemini CLI), Windows / WSL2
notes — all in [`docs/INSTALL.md`](docs/INSTALL.md).

## What is BrainPalace

BrainPalace indexes your codebase and documentation, then exposes the
resulting search over multiple interfaces so any AI assistant — or you
yourself — can answer questions against it. On top of plain retrieval it
keeps **persistent memory**: curated facts, captured coding-session summaries
and decisions, and a **temporal knowledge graph** that tracks how those
decisions supersede each other over time. Local-first by default (Ollama),
with optional cloud providers for embeddings and summarisation.

| Component | What it does |
|-----------|--------------|
| **Server** (`brainpalace-rag`) | FastAPI backend — indexing pipeline, BM25 + vector + GraphRAG stores, REST API |
| **CLI** (`brainpalace-cli`) | Click-based command-line client; primary interface for automation, mono-repos, and standalone use |
| **MCP server** (`brainpalace mcp`) | Opt-in stdio shim for non-Claude-Code AI clients (VS Code / Copilot, Cursor, Kilo Code, Cline, Continue, Zed) |
| **Claude Code plugin** | 30 slash commands, 3 agents, 2 skills for Claude Code users |

## Features

- **Hybrid search** — BM25 + vector + GraphRAG, fused per query (`hybrid`,
  `multi`) or selectable per call (`bm25`, `vector`, `graph`).
- **Session intelligence** — capture AI-coding sessions into curated memory
  (`remember`/`recall`, markdown source-of-truth), searchable summaries +
  decisions, and a **typed knowledge graph** (Decision / Error / File / …).
  Cross-session linking supersedes stale decisions and promotes durable ones
  into memory. **Automatic (passive) capture indexes Claude Code transcripts
  only** (`~/.claude/projects/…/*.jsonl`) — it's a *server* feature, so it works
  from **either install** (CLI-only or the plugin); no plugin required — it's
  **on by default for new projects** (`brainpalace init`; opt out with
  `init --no-sessions`). "Claude Code-specific" is about the transcript
  *source*, not the install method. Other runtimes (OpenCode, Gemini CLI, Codex)
  have no passive capture — they push memory explicitly via the plugin's
  `/brainpalace-extract-session`. See [SESSION_INDEXING](docs/SESSION_INDEXING.md).
- **Session summarization — `subagent` default (Claude-Code-only)** — `init`
  writes `mode: subagent`: sessions are summarized **only inside Claude Code**
  (the plugin, free on your Claude Code subscription — Haiku, after your first
  turn, drawing on your subscription's usage limits, no separate API bill; it
  owns its hooks). **The server never summarizes on its own** — no surprise API
  bill; if Claude Code didn't summarize a session, it stays un-summarized. Opt
  in to server-side summarization with `mode: provider` (your configured AI;
  prefer local Ollama — free + private) or `mode: auto` (defer to the plugin,
  server fallback with a 24h safety net). Under `provider`/`auto`, no session is
  ever silently skipped (retry + catch-up sweep + durable queue); a unified
  `.done` marker means flips never double-summarize. `backfill-sessions`
  summarizes old chats.
- **Persistent graph backend** — opt-in `store_type: sqlite` with **temporal
  validity** (per-edge validity windows, `invalidate`, `timeline`); scales past
  the in-memory default. See [GRAPHRAG_GUIDE](docs/GRAPHRAG_GUIDE.md).
- **Time-decay ranking** — newer chunks rank higher (configurable half-life).
- **Git-history indexing** — commit messages + diff stats as a searchable
  source, bridging *why* ↔ *what*. See [GIT_HISTORY](docs/GIT_HISTORY.md).
- **LSP cross-references** (opt-in) — typed `calls`/`extends`/`implements`
  symbol graph from a real language server. See
  [LSP_INTEGRATION](docs/LSP_INTEGRATION.md).
- **AST-aware code chunking** — tree-sitter for Python, TypeScript,
  JavaScript, Java, Kotlin, C, C++, C#, Go, Rust, Swift.
- **LLM code summaries** — optional AI-generated per-chunk descriptions to
  lift semantic recall on code.
- **GraphRAG** — entity + relationship extraction. Dependency-aware
  queries: "what calls X", "modules importing Y", "classes extending Z".
- **Cross-encoder reranking** — opt-in two-stage retrieval for higher
  precision on the top-k.
- **`.gitignore`-aware indexing + watching** — every project `.gitignore`
  (nested files, negation patterns) honoured at index and watch time.
- **File watcher** — per-folder, debounced, post-enqueue cooldown.
  Default OFF, opt-in per folder (`auto`).
- **Multi-instance** — one server per project, automatic port allocation,
  `.brainpalace/runtime.json` discovery. Helpers: `whoami`, `status --all`,
  `stop --url`.
- **URL auto-discovery** — CLI walks up from CWD to the owning server.
  Works correctly in mono-repos.
- **Incremental indexing** — manifest + SHA-256; only changed files
  re-embed; chunk eviction tracks deletes.
- **Embedding cache** — TTL 3600 s, hit-rate tracked. Cuts provider cost
  on reindex.
- **Pluggable providers** — embeddings (OpenAI · Cohere · Ollama),
  summarisation (Anthropic · OpenAI · Gemini · Grok · Ollama). Fully
  local mode via Ollama for both.

## Search Modes

| Mode | Best For | Example Query |
|------|----------|---------------|
| `HYBRID` | General questions (default) | "How does caching work?" |
| `VECTOR` | Conceptual understanding | "Explain the architecture" |
| `BM25` | Exact terms, error codes | "NullPointerException", "getUserById" |
| `GRAPH` | Relationships, dependencies | "What classes use AuthService?" |
| `MULTI` | Comprehensive search (all modes via RRF) | "Everything about data validation" |

## Usage Examples

Four everyday queries and the kind of output to expect. The server is
auto-discovered from your current directory — no `--url` flag needed. (Results
below are illustrative.)

### 1. Search your codebase

```bash
brainpalace query "where is the JWT token expiry validated?" --mode hybrid --top-k 3
```

```
Query: where is the JWT token expiry validated?
Found 3 results in 412ms

╭─ [1] src/auth/middleware.py  (score 0.87) ─────────────────────────────╮
│ def verify_token(token: str) -> Claims:                                │
│     claims = decode(token, SECRET, algorithms=["HS256"])               │
│     if claims.exp <= now():            # expiry check                   │
│         raise TokenExpired()                                            │
╰─────────────────────────────────────────────────────────────────────────╯
╭─ [2] src/auth/claims.py  (score 0.71) ─────────────────────────────────╮
│ class Claims(BaseModel):                                                │
│     exp: int   # unix epoch; compared in verify_token()                 │
╰─────────────────────────────────────────────────────────────────────────╯
```

### 2. Search your docs

```bash
brainpalace query "what is the embedding cache TTL?" --mode vector --top-k 2
```

```
Query: what is the embedding cache TTL?
Found 2 results in 233ms

╭─ [1] docs/ARCHITECTURE.md  (score 0.81) ───────────────────────────────╮
│ The embedding cache holds vectors for 3600 s (1 h) by default, keyed    │
│ by provider:model:text-hash. Hit rate is reported in `status`.          │
╰─────────────────────────────────────────────────────────────────────────╯
```

### 3. Trace dependencies (graph search)

Relationship-aware queries — "what calls X", "what imports Y", "what extends Z".
`--mode graph` walks the extracted entity/relationship graph instead of ranking
text:

```bash
brainpalace query "what calls QueryService.search?" --mode graph --top-k 3
```

```
Query: what calls QueryService.search?
Found 3 results in 388ms

╭─ [1] api/routers/query.py  (graph: CALLS) ─────────────────────────────╮
│ async def search(req: QueryRequest, svc = Depends(get_query_service)):  │
│     return await svc.search(req.query)    # endpoint → QueryService     │
╰─────────────────────────────────────────────────────────────────────────╯
╭─ [2] services/research_agent.py  (graph: CALLS) ───────────────────────╮
│ hits = self.query_service.search(q, mode="multi")                       │
│   edge: ResearchAgent ──CALLS──▶ QueryService.search                    │
╰─────────────────────────────────────────────────────────────────────────╯
╭─ [3] cli/commands/query.py  (graph: CALLS) ────────────────────────────╮
│ results = client.search(text, mode=mode)                                │
╰─────────────────────────────────────────────────────────────────────────╯
```

### 4. Search past coding sessions (session memory)

Recall decisions and context from earlier AI-coding sessions. Restrict the
search to session chunks with `--source-types session_turn`:

```bash
brainpalace query "why did we switch the queue from redis to sqlite?" \
  --source-types session_turn --top-k 2
```

```
Query: why did we switch the queue from redis to sqlite?
Found 2 results in 540ms

╭─ [1] session 2026-05-18  (score 0.79) ─────────────────────────────────╮
│ assistant: Dropping Redis for the job queue — the single-process server │
│ made the extra daemon pure overhead. SQLite WAL gives durability with   │
│ zero ops. Migrated JobQueueStore in this session.                       │
│   tools: Edit(job_queue.py)  ·  branch: stable                          │
╰─────────────────────────────────────────────────────────────────────────╯
```

> **What "session memory" needs.** Automatic capture indexes **Claude Code
> transcripts only** (`~/.claude/projects/<encoded>/*.jsonl`). It's a **server**
> feature — it works whether you installed BrainPalace via the **CLI** or as the
> **Claude Code plugin** (no plugin required); enable it with `brainpalace init
> --sessions` (opt-in, off by default). The Claude-Code restriction is about the
> *transcript format it reads*, not how you installed BrainPalace. Other runtimes
> (OpenCode, Gemini CLI, Codex) have no passive capture — they push durable memory
> explicitly via the plugin's runtime-agnostic `/brainpalace-extract-session`.
> See [SESSION_INDEXING](docs/SESSION_INDEXING.md).

## Pluggable Providers

### Embedding Providers
| Provider | Models | Local |
|----------|--------|-------|
| OpenAI | text-embedding-3-large, text-embedding-3-small | No |
| Cohere | embed-english-v3.0, embed-multilingual-v3.0 | No |
| Ollama | nomic-embed-text, mxbai-embed-large | Yes |

### Summarisation Providers
| Provider | Models | Local |
|----------|--------|-------|
| Anthropic | claude-haiku-4-5-20251001, claude-sonnet-4-5-20250514 | No |
| OpenAI | gpt-5, gpt-5-mini | No |
| Gemini | gemini-3-flash, gemini-3-pro | No |
| Grok | grok-4, grok-4-fast | No |
| Ollama | llama4:scout, mistral-small3.2, qwen3-coder | Yes |

### Fully Local Mode

Run completely offline with Ollama for both embeddings and summarisation:

```
/brainpalace-providers
# Pick Ollama for both
```

Or via the CLI: [docs/PROVIDER_CONFIGURATION.md](docs/PROVIDER_CONFIGURATION.md).

## Claude Code Plugin

The plugin ships **30 slash commands**, **3 agents**, and **2 skills**.
Full reference: [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md).

| Category | Commands |
|---|---|
| Search | `/brainpalace-search`, `/brainpalace-semantic`, `/brainpalace-vector`, `/brainpalace-keyword`, `/brainpalace-bm25`, `/brainpalace-hybrid`, `/brainpalace-graph`, `/brainpalace-multi` |
| Server | `/brainpalace-start`, `/brainpalace-stop`, `/brainpalace-status`, `/brainpalace-list` |
| Index | `/brainpalace-index`, `/brainpalace-folders`, `/brainpalace-inject`, `/brainpalace-reset`, `/brainpalace-types` |
| Setup | `/brainpalace-setup`, `/brainpalace-install`, `/brainpalace-init`, `/brainpalace-verify`, `/brainpalace-providers` |

| Agent | Role |
|---|---|
| Search Assistant | Multi-step search across modes; synthesises answers with citations |
| Research Assistant | Deep exploration with follow-up queries |
| Setup Assistant | Guided installation and troubleshooting |

| Skill | Purpose |
|---|---|
| `using-brainpalace` | Search-mode selection, query optimisation, API knowledge |
| `configuring-brainpalace` | Installation, provider configuration, troubleshooting |

## Project Structure

```
brainpalace/
├── brainpalace-plugin/                     # Claude Code plugin
│   ├── commands/                            # 30 slash commands
│   ├── agents/                              # 3 intelligent agents
│   ├── skills/                              # 2 context skills
│   └── templates/                           # mcp-config-claude-code.json + sessionstart hook
├── brainpalace-server/                     # FastAPI backend (REST API)
├── brainpalace-cli/                        # CLI + Python SDK + MCP shim
│   └── brainpalace_cli/
│       ├── commands/                        # CLI subcommands incl. `mcp`
│       ├── mcp_server/                      # Opt-in MCP stdio shim
│       └── client/                          # Python SDK
└── docs/                                    # User + developer docs
```

## Documentation

### Getting Started
- [Install (alternative paths)](docs/INSTALL.md) — manual / CI / other AI runtimes / low-level flags
- [Quick Start](docs/QUICK_START.md) — first-run walkthrough
- [MCP Setup](docs/MCP_SETUP.md) — per-client config for non-Claude-Code AI clients
- [Plugin Guide](docs/PLUGIN_GUIDE.md) — full Claude Code plugin reference
- [User Guide](docs/USER_GUIDE.md) — CLI usage and feature reference

### Reference
- [API Reference](docs/API_REFERENCE.md) — REST API documentation
- [Configuration](docs/CONFIGURATION.md) — config.yaml options
- [Provider Configuration](docs/PROVIDER_CONFIGURATION.md) — embedding + summarisation provider setup
- [Changelog](docs/CHANGELOG.md) — per-version notes

### Architecture
- [Architecture Overview](docs/ARCHITECTURE.md) — components, data flow
- [GraphRAG Guide](docs/GRAPHRAG_GUIDE.md) — knowledge-graph features
- [Code Indexing](docs/CODE_INDEXING.md) — AST-aware chunking
- [Deployment](docs/DEPLOYMENT.md) — local + production deployment
- [Developer Guide](docs/DEVELOPERS_GUIDE.md) — monorepo layout, sub-modules, contributing

## Development

```bash
git clone https://github.com/bxw91/brainpalace.git
cd brainpalace
task install
task before-push      # full quality gate — mandatory before merge
```

Full setup and contribution workflow:
[docs/DEVELOPERS_GUIDE.md](docs/DEVELOPERS_GUIDE.md).

## Technology Stack

- **Server**: FastAPI + Uvicorn
- **Vector Store**: ChromaDB (HNSW, cosine similarity)
- **BM25 Index**: LlamaIndex BM25Retriever
- **Graph Store**: LlamaIndex SimplePropertyGraphStore (JSON) or SQLite (persistent, temporal)
- **Embeddings**: OpenAI · Cohere · Ollama
- **Summarisation**: Anthropic · OpenAI · Gemini · Grok · Ollama
- **AST Parsing**: tree-sitter (10+ languages)
- **CLI**: Click + Rich
- **MCP**: Anthropic `mcp` SDK (stdio transport)
- **Build**: Poetry

## Contributing

PRs land on `stable`. Before pushing, `task before-push` must pass. See
[docs/DEVELOPERS_GUIDE.md](docs/DEVELOPERS_GUIDE.md) for monorepo layout, test
commands, and release discipline.

## License

MIT — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for details.

## Links

- [Releases](https://github.com/bxw91/brainpalace/releases)
- [Issues](https://github.com/bxw91/brainpalace/issues)
